# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2.5.4",
#     "scikit-learn>=1.9.1",
#     "sentence-transformers>=6.2.0",
#     "torch>=2.15.0",
#     "umap-learn>=0.5.12",
#     "pacmap>=0.9.1",
#     "pyarrow",
# ]
# ///
"""次元削減(PCA / UMAP / PaCMAP / t-SNE)が、日本語の話題クラスタリングを良くするかを測る。

    uv run evals/dr_bench.py                                   # 既定: 2設定 × 2サンプル × 5シード
    uv run evals/dr_bench.py --settings title --subs 0 --seeds 0   # 動作確認(短い)

結果と読み方は docs/dimensionality-reduction.md にある。

データ: livedoor ニュースコーパス(CC BY-ND 2.1 JP。https://www.rondhuit.com/download.html)。
Hugging Face の llm-book/livedoor-news-corpus の parquet 版を、初回に取得する。評価にだけ使い、再配布しない。
データ・埋め込みのキャッシュ・結果は feedback/dr-bench/ に置く(Git の対象外)。

埋め込み・silhouette は本番(scripts/mece_cluster.py)の関数を使う。silhouette は、次元削減の前の
cosine 距離で測る(次元削減後の空間で測ると、削減の歪みを自分で褒めてしまう)。

UMAP / PaCMAP(numba・faiss)を torch と同じプロセスに読み込むと、macOS で SIGSEGV になった。
そのため、埋め込みは別のプロセスで先に計算し、評価はキャッシュから行う(自動で分ける)。
"""

import argparse
import hashlib
import http.client
import json
import subprocess
import sys
import time
import urllib.request
import warnings
from datetime import date
from importlib import metadata
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from mece_cluster import DEFAULT_MODEL, cosine_distance, embed, embedding_prefix, silhouette  # noqa: E402

warnings.filterwarnings("ignore")
OUT = ROOT / "feedback" / "dr-bench"
URL = "https://huggingface.co/datasets/llm-book/livedoor-news-corpus/resolve/refs%2Fconvert%2Fparquet/livedoor-news-corpus/train/0000.parquet"
K_TRUE, K_RANGE = 9, range(2, 13)  # 自動 k の探索範囲。本番の既定(--k-max 8)より広く、正解の 9 を選べるようにしてある
PER_CATEGORY = 100


def load_rows() -> list[dict]:
    path = OUT / "data" / "train.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(URL, timeout=60) as resp:
                    want = int(resp.headers["Content-Length"])
                    body = resp.read()
            except (OSError, http.client.HTTPException) as e:  # 途中切断(IncompleteRead)・タイムアウトも再試行する
                print(f"download failed ({e!r}), retry {attempt}", file=sys.stderr)
                continue
            if len(body) == want and body[:4] == b"PAR1" and body[-4:] == b"PAR1":  # 途中で切れたファイルを残さない
                path.write_bytes(body)
                break
            print(f"download incomplete ({len(body)}/{want}), retry {attempt}", file=sys.stderr)
        else:
            raise SystemExit("error: ダウンロードが完了しない")
    return pq.read_table(path).to_pylist()


def sample(rows: list[dict], sub: int, per: int = PER_CATEGORY) -> list[dict]:
    """カテゴリごとに per 件を無作為に取る(sub がサンプルの番号)。"""
    rng = np.random.default_rng(1000 + sub)
    out = []
    for c in sorted({r["category"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["category"] == c]
        out += [rows[i] for i in rng.choice(idx, per, replace=False)]
    return out


def make_text(r: dict, setting: str) -> str:
    """title はタイトルだけ(短い項目)。lead はタイトルに本文の先頭150字を足す。"""
    title = " ".join(r["title"].split())
    if setting == "title":
        return title
    return title + " " + " ".join(r["content"].split())[:150]


def cache_path(rows: list[dict], setting: str, sub: int) -> Path:
    """埋め込みの入力(モデル・接頭辞・設定・サンプル・データの行数)が変わると、別のファイルになる。"""
    spec = f"{DEFAULT_MODEL}|{embedding_prefix(DEFAULT_MODEL, None)}|{setting}|{sub}|{PER_CATEGORY}|{len(rows)}"
    return OUT / "cache" / f"emb_{setting}_{sub}_{hashlib.sha1(spec.encode()).hexdigest()[:8]}.npy"


def model_revision() -> str:
    """埋め込みに使ったモデルの版(Hugging Face のキャッシュのリビジョン)。本番と同じく main を取るので、固定はしない。"""
    try:
        from huggingface_hub import snapshot_download

        return Path(snapshot_download(DEFAULT_MODEL, local_files_only=True)).name
    except Exception:
        return "unknown"


def cache_valid(rows: list[dict], setting: str, sub: int) -> bool:
    """埋め込みのキャッシュがあり、作ったときのモデルのリビジョンが、今の Hugging Face のキャッシュと同じか。"""
    cache = cache_path(rows, setting, sub)
    side = cache.with_suffix(".json")
    if not (cache.exists() and side.exists()):
        return False
    try:
        return json.loads(side.read_text(encoding="utf-8")).get("revision") == model_revision()
    except (OSError, ValueError):
        return False


def get_emb(rows: list[dict], setting: str, sub: int, embed_ok: bool = True) -> tuple[np.ndarray, np.ndarray]:
    sel = sample(rows, sub)
    y = np.array([r["category"] for r in sel])
    cache = cache_path(rows, setting, sub)
    if cache_valid(rows, setting, sub):
        return np.load(cache), y
    if not embed_ok:  # 評価のプロセスで torch を読むと、UMAP / PaCMAP と衝突して落ちる
        raise SystemExit("error: 埋め込みのキャッシュが無い・古い。--embed-only を先に実行する。")
    side = cache.with_suffix(".json")
    cache.parent.mkdir(parents=True, exist_ok=True)
    texts = [make_text(r, setting) for r in sel]
    emb, _ = embed(texts, DEFAULT_MODEL, embedding_prefix(DEFAULT_MODEL, None), device="cpu")
    np.save(cache, emb)
    side.write_text(json.dumps({"revision": model_revision()}), encoding="utf-8")
    return emb, y


def build_methods() -> dict:
    # umap / pacmap は torch と同じプロセスに読み込むと macOS で落ちる(SIGSEGV)ため、埋め込みの後に別プロセスで読む
    import pacmap
    import umap

    methods = {"raw": lambda e, s: e}
    for d in (16, 32, 64, 128):
        methods[f"pca{d}"] = lambda e, s, d=d: PCA(d, random_state=s).fit_transform(e)
    methods["pca64w"] = lambda e, s: PCA(64, whiten=True, random_state=s).fit_transform(e)
    for d in (5, 10, 15):
        methods[f"umap{d}"] = lambda e, s, d=d: umap.UMAP(
            n_components=d, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=s
        ).fit_transform(e)
        methods[f"pacmap{d}"] = lambda e, s, d=d: pacmap.PaCMAP(n_components=d, random_state=s).fit_transform(e)
    # t-SNE は scikit-learn のもの(Barnes-Hut 法のため 3 次元まで)。perplexity は 30 を基準に、2 次元で 15 と 50 も見る
    for name, d, p in (("tsne2", 2, 30), ("tsne3", 3, 30), ("tsne2p15", 2, 15), ("tsne2p50", 2, 50)):
        methods[name] = lambda e, s, d=d, p=p: TSNE(
            n_components=d, perplexity=p, metric="cosine", init="pca", random_state=s
        ).fit_transform(e)
    return methods


def evaluate(x: np.ndarray, dist: np.ndarray, y: np.ndarray, make_labels) -> dict:
    """k=9(正解の数)と、本番どおり silhouette で選んだ k の両方で測る。silhouette は元の cosine 距離。"""
    labs = {k: make_labels(x, k) for k in K_RANGE}
    sil = {k: float(silhouette(dist, labs[k])[0].mean()) for k in K_RANGE}
    kb = max(sil, key=lambda k: (sil[k], -k))
    return {
        "ari9": adjusted_rand_score(y, labs[K_TRUE]),
        "nmi9": normalized_mutual_info_score(y, labs[K_TRUE]),
        "sil9": sil[K_TRUE],
        "k_auto": kb,
        "ari_auto": adjusted_rand_score(y, labs[kb]),
    }


def ensure_embeddings(rows: list[dict], settings: list[str], subs: list[int]) -> None:
    """未計算の埋め込みを、別プロセスで先に計算する。"""
    # 1回目の計算でモデルを取得し直すと、先に再利用した分のリビジョンが古くなる。そのため、最大2回まで作り直す。
    for _ in range(2):
        if all(cache_valid(rows, s, b) for s in settings for b in subs):
            return
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--embed-only", "--settings", *settings, "--subs", *map(str, subs)],
            check=True,
        )
    if not all(cache_valid(rows, s, b) for s in settings for b in subs):
        raise SystemExit("error: 埋め込みを作り直しても、キャッシュが有効にならない。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", nargs="+", default=["title", "lead"])
    ap.add_argument("--subs", nargs="+", type=int, default=[0, 1])
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    ap.add_argument("--embed-only", action="store_true", help="埋め込みだけ計算してキャッシュする(内部で使う)")
    args = ap.parse_args()

    if args.embed_only:
        rows = load_rows()
        for setting in args.settings:
            for sub in args.subs:
                get_emb(rows, setting, sub)
        return

    rows = load_rows()
    ensure_embeddings(rows, args.settings, args.subs)
    methods = build_methods()
    records = []
    for setting in args.settings:
        for sub in args.subs:
            emb, y = get_emb(rows, setting, sub, embed_ok=False)
            yi = np.unique(y, return_inverse=True)[1]
            dist = cosine_distance(emb)
            print(f"[{setting} sub{sub}] n={len(emb)} dim={emb.shape[1]}", file=sys.stderr)

            # 乱数に依存しない手法は1回だけ
            for name, kw in (("agg-average", {"linkage": "average", "metric": "cosine"}), ("agg-ward", {"linkage": "ward"})):
                r = evaluate(emb, dist, yi, lambda x, k, kw=kw: AgglomerativeClustering(n_clusters=k, **kw).fit_predict(x))
                records.append({"setting": setting, "sub": sub, "seed": -1, "method": name, "time": 0.0, **r})

            for seed in args.seeds:
                for name, fn in methods.items():
                    t0 = time.time()
                    x = fn(emb, seed)
                    dt = time.time() - t0
                    r = evaluate(x, dist, yi, lambda z, k, s=seed: KMeans(n_clusters=k, n_init=10, random_state=s).fit_predict(z))
                    rec = {"setting": setting, "sub": sub, "seed": seed, "method": name, "time": dt, **r}
                    if name in ("umap10", "pacmap10", "raw"):
                        h = HDBSCAN(min_cluster_size=10).fit_predict(x)
                        rec["hdb_noise"] = float((h == -1).mean())
                        rec["hdb_clusters"] = int(h.max() + 1)
                        rec["hdb_ari"] = adjusted_rand_score(yi, h)
                    records.append(rec)
                print(f"  seed {seed} done", file=sys.stderr)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "records.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    for setting in args.settings:
        print(f"\n## {setting}")
        print(f"{'method':<14}{'ARI(k=9)':>16}{'NMI(k=9)':>16}{'sil(k=9)':>10}{'k_auto':>8}{'ARI(auto)':>16}{'sec':>7}")
        for m in dict.fromkeys(r["method"] for r in records):
            rs = [r for r in records if r["setting"] == setting and r["method"] == m]
            if not rs:
                continue
            f = lambda key: (np.mean([r[key] for r in rs]), np.std([r[key] for r in rs]))
            a, n, s, ka, aa = f("ari9"), f("nmi9"), f("sil9"), f("k_auto"), f("ari_auto")
            print(f"{m:<14}{a[0]:>10.3f}±{a[1]:.3f}{n[0]:>10.3f}±{n[1]:.3f}{s[0]:>10.3f}{ka[0]:>8.1f}{aa[0]:>10.3f}±{aa[1]:.3f}{np.mean([r['time'] for r in rs]):>7.1f}")
        for m in ("raw", "umap10", "pacmap10"):
            rs = [r for r in records if r["setting"] == setting and r["method"] == m and "hdb_ari" in r]
            if rs:
                print(f"HDBSCAN on {m}: noise={np.mean([r['hdb_noise'] for r in rs]):.2f} clusters={np.mean([r['hdb_clusters'] for r in rs]):.1f} ARI={np.mean([r['hdb_ari'] for r in rs]):.3f}")

    # 生の埋め込みとの、同じサンプル・同じシードでの差(対応のある差)
    key = lambda r: (r["setting"], r["sub"], r["seed"])
    raw = {key(r): r for r in records if r["method"] == "raw"}
    print("\n## 生の埋め込みとの差(ARI, k=9。平均 ± 標準誤差 [上回った組/全体])")
    for m in ("pca32", "pca64", "pca64w", "umap5", "umap10", "umap15", "pacmap5", "pacmap10", "pacmap15", "tsne2", "tsne3", "tsne2p15", "tsne2p50"):
        d = [r["ari9"] - raw[key(r)]["ari9"] for r in records if r["method"] == m and key(r) in raw]
        if len(d) > 1:
            print(f"{m:<9} {np.mean(d):+.3f} ± {np.std(d, ddof=1) / np.sqrt(len(d)):.3f}  [{sum(x > 0 for x in d)}/{len(d)}]")
    print("(標準誤差は、組を独立とみなした値。同じサンプルを共有する組は独立でないので、不確かさは小さく見える。目安として読む)")

    print("\n## 生の埋め込みとの差(ARI, k=9。設定・サンプル別。シードの平均)")
    for m in ("pca32", "umap10", "pacmap10", "tsne2", "tsne3"):
        cells = []
        for setting in args.settings:
            for sub in args.subs:
                d = [r["ari9"] - raw[key(r)]["ari9"] for r in records if r["method"] == m and r["setting"] == setting and r["sub"] == sub]
                cells.append(f"{setting}/sub{sub}: {np.mean(d):+.3f}")
        print(f"{m:<9} " + "  ".join(cells))

    meta = {
        "date": date.today().isoformat(),
        "model": DEFAULT_MODEL,
        "revision": model_revision(),
        "prefix": embedding_prefix(DEFAULT_MODEL, None),
        "per_category": PER_CATEGORY,
        "k_range": [K_RANGE.start, K_RANGE.stop - 1],
        "settings": args.settings,
        "subs": args.subs,
        "seeds": args.seeds,
        "python": sys.version.split()[0],
        "versions": {p: metadata.version(p) for p in ("numpy", "scikit-learn", "torch", "sentence-transformers", "umap-learn", "pacmap")},
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nmodel revision: {meta['revision']}  (meta.json に版と条件を保存)")
    print(f"TSNE.transform の有無(新しい項目を後から変換できるか): {hasattr(TSNE, 'transform')}")


if __name__ == "__main__":
    main()
