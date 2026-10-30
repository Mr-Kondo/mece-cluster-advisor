# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2.5.4",
#     "scikit-learn>=1.9.1",
#     "sentence-transformers>=6.2.0",
#     "torch>=2.15.0",
#     "umap-learn>=0.5.12",
#     "pacmap>=0.9.1",
#     "openTSNE",
#     "pyarrow",
# ]
# ///
"""次元削減の評価(evals/dr_bench.py)を広げる。結果と読み方は docs/dimensionality-reduction.md にある。

    uv run evals/dr_extend.py scale --dataset livedoor --per-class 500      # 件数を増やす(4,500 件)
    uv run evals/dr_extend.py scale --dataset livedoor --model cl-nagoya/ruri-v3-30m   # 別のモデル
    uv run evals/dr_extend.py scale --dataset massive                       # 口語の短文(JMTEB の MASSIVE ja)
    uv run evals/dr_extend.py tsne                                          # t-SNE の乱数・調整・openTSNE

データ: livedoor ニュースコーパス(CC BY-ND 2.1 JP)、JMTEB の massive_scenario_classification(MASSIVE、CC BY 4.0)。
評価にだけ使い、再配布しない。取得したデータ・埋め込みのキャッシュ・結果は feedback/dr-extend/ に置く(Git の対象外)。

UMAP / PaCMAP と torch を同じプロセスに読み込むと macOS で落ちる(dr_bench.py と同じ)ので、埋め込みは別のプロセスで先に計算する。
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
import warnings
from collections import Counter
from importlib import metadata
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import adjusted_rand_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dr_bench  # noqa: E402
from mece_cluster import DEFAULT_MODEL, cosine_distance, embed, embedding_prefix, silhouette  # noqa: E402

warnings.filterwarnings("ignore")
OUT = ROOT / "feedback" / "dr-extend"
MASSIVE_URL = "https://huggingface.co/datasets/sbintuitions/JMTEB/resolve/refs%2Fconvert%2Fparquet/massive_scenario_classification/train/0000.parquet"


# ---------------------------------------------------------------- データと埋め込み
def load_items(dataset: str, per_class: int, sub: int, setting: str) -> tuple[list[str], np.ndarray]:
    """(テキスト, 正解ラベル)。クラスごとに同じ件数を、sub ごとに別の乱数で取る。"""
    if dataset == "livedoor":
        rows = dr_bench.load_rows()
        smallest = min(Counter(r["category"] for r in rows).values())
        sel = dr_bench.sample(rows, sub, min(per_class, smallest))  # 小さいカテゴリに合わせる
        return [dr_bench.make_text(r, setting) for r in sel], np.array([r["category"] for r in sel])
    path = OUT / "data" / "massive_train.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(MASSIVE_URL, timeout=120) as resp:
            path.write_bytes(resp.read())
    rows = pq.read_table(path).to_pylist()
    rng = np.random.default_rng(1000 + sub)
    labels = sorted({r["label_text"] for r in rows})
    per = min(per_class, min(sum(r["label_text"] == c for r in rows) for c in labels))
    sel = []
    for c in labels:
        idx = [i for i, r in enumerate(rows) if r["label_text"] == c]
        sel += [rows[i] for i in rng.choice(idx, per, replace=False)]
    return [" ".join(r["text"].split()) for r in sel], np.array([r["label_text"] for r in sel])


def get_emb(args, sub: int, embed_ok: bool) -> tuple[np.ndarray, np.ndarray]:
    setting = args.setting if args.dataset == "livedoor" else "-"  # massive に設定は無い
    texts, y = load_items(args.dataset, args.per_class, sub, setting)
    spec = f"{args.dataset}|{args.model}|{setting}|{args.per_class}|{sub}|{len(texts)}|{hashlib.sha1('|'.join(texts).encode()).hexdigest()}"
    cache = OUT / "cache" / f"emb_{hashlib.sha1(spec.encode()).hexdigest()[:10]}.npy"
    if cache.exists():
        return np.load(cache), y
    if not embed_ok:
        raise SystemExit("error: 埋め込みのキャッシュが無い。")
    cache.parent.mkdir(parents=True, exist_ok=True)
    emb, dev = embed(texts, args.model, embedding_prefix(args.model, None), device="auto")
    np.save(cache, emb)
    print(f"embedded {len(texts)} items on {dev}", file=sys.stderr)
    return emb, y


# ---------------------------------------------------------------- 手法と評価
def methods(names: list[str]) -> dict:
    import pacmap
    import umap

    all_ = {
        "raw": lambda e, s: e,
        "pca32": lambda e, s: PCA(32, random_state=s).fit_transform(e),
        "umap10": lambda e, s: umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=s).fit_transform(e),
        "pacmap10": lambda e, s: pacmap.PaCMAP(n_components=10, random_state=s).fit_transform(e),
        "tsne2": lambda e, s: TSNE(2, perplexity=30, metric="cosine", init="pca", random_state=s).fit_transform(e),
    }
    return {n: all_[n] for n in names}


def evaluate(x: np.ndarray, dist: np.ndarray, yi: np.ndarray, km_seed: int, k_true: int) -> dict:
    """正解の数 k での ARI と、本番どおり silhouette(元の cosine 距離)で選んだ k での ARI。"""
    labs = {k: KMeans(n_clusters=k, n_init=10, random_state=km_seed).fit_predict(x) for k in range(2, k_true + 4)}
    sil = {k: float(silhouette(dist, labs[k])[0].mean()) for k in labs}
    ka = max(sil, key=lambda k: (sil[k], -k))
    return {"ari": adjusted_rand_score(yi, labs[k_true]), "k_auto": ka, "ari_auto": adjusted_rand_score(yi, labs[ka])}


def paired(records: list[dict], key, base: str, name: str, field: str = "ari") -> str:
    b = {key(r): r[field] for r in records if r["method"] == base}
    d = [r[field] - b[key(r)] for r in records if r["method"] == name and key(r) in b]
    if len(d) < 2:
        return f"{name:<14} (n={len(d)})"
    return f"{name:<14} {np.mean(d):+.3f} ± {np.std(d, ddof=1) / np.sqrt(len(d)):.3f}  [{sum(x > 0 for x in d)}/{len(d)}]"


# ---------------------------------------------------------------- scale: 件数・モデル・データを変える
def run_scale(args) -> None:
    if args.embed_only:
        for sub in args.subs:
            get_emb(args, sub, embed_ok=True)
        return
    try:  # 埋め込みが無ければ、別プロセスで先に作る
        for sub in args.subs:
            get_emb(args, sub, embed_ok=False)
    except SystemExit:
        subprocess.run([sys.executable, __file__, "scale", "--embed-only", *sys.argv[2:]], check=True)
    ms = methods(args.methods)
    records = []
    for sub in args.subs:
        emb, y = get_emb(args, sub, embed_ok=False)
        yi = np.unique(y, return_inverse=True)[1]
        k_true = int(yi.max() + 1)
        dist = cosine_distance(emb)
        print(f"[sub{sub}] n={len(emb)} dim={emb.shape[1]} classes={k_true}", file=sys.stderr)
        for seed in args.seeds:
            for name, fn in ms.items():
                t0 = time.time()
                x = fn(emb, seed)
                dt = time.time() - t0
                records.append({"sub": sub, "seed": seed, "method": name, "time": dt, "n": len(emb), **evaluate(x, dist, yi, seed, k_true)})
            print(f"  seed {seed} done", file=sys.stderr)
    tag = f"scale_{args.dataset}_{args.setting if args.dataset == 'livedoor' else '-'}_{args.model.split('/')[-1]}_{args.per_class}"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{tag}.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    print(f"\n## {tag}  (n={records[0]['n']}, 正解のクラス数 {k_true})")
    print(f"{'method':<10}{'ARI(正解k)':>16}{'k_auto':>8}{'ARI(auto)':>16}{'sec':>7}")
    for m in ms:
        rs = [r for r in records if r["method"] == m]
        print(f"{m:<10}{np.mean([r['ari'] for r in rs]):>10.3f}±{np.std([r['ari'] for r in rs]):.3f}{np.mean([r['k_auto'] for r in rs]):>8.1f}"
              f"{np.mean([r['ari_auto'] for r in rs]):>10.3f}±{np.std([r['ari_auto'] for r in rs]):.3f}{np.mean([r['time'] for r in rs]):>7.1f}")
    key = lambda r: (r["sub"], r["seed"])
    print("\n生の埋め込みとの差(ARI 正解k。平均 ± 標準誤差 [上回った組/全体])")
    for m in ms:
        if m != "raw":
            print(paired(records, key, "raw", m))
    print("生の埋め込みとの差(ARI auto)")
    for m in ms:
        if m != "raw":
            print(paired(records, key, "raw", m, "ari_auto"))
    print("versions:", {p: metadata.version(p) for p in ("numpy", "scikit-learn", "torch", "sentence-transformers", "umap-learn", "pacmap")})


# ---------------------------------------------------------------- tsne: 乱数・調整・openTSNE
def run_tsne(args) -> None:
    rows = dr_bench.load_rows()
    dr_bench.ensure_embeddings(rows, args.settings, args.subs)
    from openTSNE import TSNE as OTSNE

    def sk(**kw):
        base = dict(n_components=2, perplexity=30, metric="cosine", init="pca")
        return lambda e, s: TSNE(**{**base, **kw}, random_state=s).fit_transform(e)

    variants = {
        "sk-p30(基準)": sk(),
        "sk-p5": sk(perplexity=5), "sk-p10": sk(perplexity=10), "sk-p100": sk(perplexity=100),
        "sk-random-init": sk(init="random"),
        "sk-lr50": sk(learning_rate=50), "sk-lr1000": sk(learning_rate=1000),
        "sk-iter250": sk(max_iter=250), "sk-iter3000": sk(max_iter=3000),
        "sk-exag4": sk(early_exaggeration=4), "sk-exag24": sk(early_exaggeration=24),
        "opentsne-p30": lambda e, s: np.asarray(OTSNE(2, perplexity=30, metric="cosine", initialization="pca", random_state=s, n_jobs=1).fit(e)),
        "opentsne-p100": lambda e, s: np.asarray(OTSNE(2, perplexity=100, metric="cosine", initialization="pca", random_state=s, n_jobs=1).fit(e)),
        "opentsne-random": lambda e, s: np.asarray(OTSNE(2, perplexity=30, metric="cosine", initialization="random", random_state=s, n_jobs=1).fit(e)),
    }
    records, seed_rows = [], []
    for setting in args.settings:
        for sub in args.subs:
            emb, y = dr_bench.get_emb(rows, setting, sub, embed_ok=False)
            yi = np.unique(y, return_inverse=True)[1]
            dist = cosine_distance(emb)
            raw_res = {s: evaluate(emb, dist, yi, s, 9) for s in args.seeds}
            raw_ari = {s: r["ari"] for s, r in raw_res.items()}
            for s in args.seeds:
                records.append({"setting": setting, "sub": sub, "seed": s, "method": "raw", **raw_res[s]})
            for name, fn in variants.items():
                for s in args.seeds:
                    r = evaluate(fn(emb, s), dist, yi, s, 9)
                    records.append({"setting": setting, "sub": sub, "seed": s, "method": name, **r})
            # 乱数の切り分け: t-SNE の乱数 × KMeans の乱数 の格子(基準の設定)
            grid = np.array([[evaluate(variants["sk-p30(基準)"](emb, ts), dist, yi, ks, 9)["ari"] for ks in args.seeds] for ts in args.seeds])
            seed_rows.append({"setting": setting, "sub": sub, "grid": grid.tolist(), "raw_by_km": [raw_ari[s] for s in args.seeds]})
            print(f"[{setting} sub{sub}] done", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tsne.json").write_text(json.dumps({"records": records, "seed_rows": seed_rows}, ensure_ascii=False), encoding="utf-8")

    key = lambda r: (r["setting"], r["sub"], r["seed"])
    print("## 生の埋め込みとの差(ARI, k=9。平均 ± 標準誤差 [上回った組/全体])")
    for name in variants:
        print(paired(records, key, "raw", name))
    print("\n## 乱数の切り分け(sk-p30。セルごとの 5×5 の ARI)")
    print(f"{'cell':<14}{'平均':>8}{'t-SNE乱数の SD':>16}{'KMeans乱数の SD':>17}{'生の KMeans乱数の SD':>22}")
    for c in seed_rows:
        g = np.array(c["grid"])  # 行: t-SNE の乱数、列: KMeans の乱数
        print(f"{c['setting'] + '/sub' + str(c['sub']):<14}{g.mean():>8.3f}{g.mean(axis=1).std(ddof=1):>16.3f}{g.mean(axis=0).std(ddof=1):>17.3f}{np.std(c['raw_by_km'], ddof=1):>22.3f}")
    print("(t-SNE乱数の SD: KMeans の乱数で平均した値の、t-SNE の乱数による標準偏差。KMeans乱数の SD: 同じく逆)")
    print("versions:", {p: metadata.version(p) for p in ("scikit-learn", "openTSNE", "numpy")})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub_ = ap.add_subparsers(dest="cmd", required=True)
    s = sub_.add_parser("scale")
    s.add_argument("--dataset", choices=["livedoor", "massive"], default="livedoor")
    s.add_argument("--model", default=DEFAULT_MODEL)
    s.add_argument("--per-class", type=int, default=100)
    s.add_argument("--setting", choices=["title", "lead"], default="lead", help="livedoor だけ")
    s.add_argument("--methods", nargs="+", default=["raw", "pca32", "umap10", "pacmap10", "tsne2"])
    s.add_argument("--subs", nargs="+", type=int, default=[0, 1])
    s.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    s.add_argument("--embed-only", action="store_true")
    t = sub_.add_parser("tsne")
    t.add_argument("--settings", nargs="+", default=["title", "lead"])
    t.add_argument("--subs", nargs="+", type=int, default=[0, 1])
    t.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    args = ap.parse_args()
    run_scale(args) if args.cmd == "scale" else run_tsne(args)


if __name__ == "__main__":
    main()
