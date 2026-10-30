#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2.5.4",
#     "scikit-learn>=1.9.1",
#     "sentence-transformers>=6.2.0",
#     "transformers>=5.22.0",
#     "torch>=2.15.0",
#     "sudachipy>=0.7.0",
#     "sudachidict-core>=20261015",
# ]
# ///
"""項目の集合を埋め込みでクラスタリングし、MECE の判断材料を JSON で出す。

    uv run mece_cluster.py items.txt --out result.json
    uv run mece_cluster.py items.csv --column comment --k 5

入力は、1行1項目のテキストか、1行目をヘッダとする CSV(--column で列を指定)。
分割を確定する道具ではない。出すのは、グループ候補、境界にある項目、境界が集中する
グループの組、グループごとのキーワードと代表項目である。軸が1つか、全体を覆っているか
(網羅性)は測れないので、呼び出し側のモデルと利用者が判断する。

LLM は呼ばない。項目のテキストは外部へ送らない。通信するのは、初回のモデル取得だけである。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

DEFAULT_MODEL = "cl-nagoya/ruri-v3-310m"
MIN_ITEMS = 4
ROOT = Path(__file__).resolve().parent.parent  # スキルのフォルダ(VERSION がある)

LIMITS = [
    "網羅性(CE)はこの出力から判定できない。何を全体とみなすかは、目的と軸で決まる。",
    "silhouette に絶対的な合格ラインはない。同じデータで k を変えたときの相対比較に使う。",
    "件数が少ないと、k の選択と境界の判定は不安定になる。",
]
# 自動選択の k は、話題の数より小さくなりやすい(docs/k-selection.md)。自動のときは、いつも知らせる
AUTO_K_NOTE = (
    "k は silhouette で自動選択した。この選び方は、実際の話題の数より小さい k を選びやすい"
    "(検証では、9カテゴリのデータで平均約4)。目的から k が決まるなら、--k で指定して再実行する。"
)

# 「1.5倍」「-5℃」のような項目の先頭は消さない。ASCII の記号は後ろに空白があるときだけ箇条書きとみなす
_BULLET = re.compile(r"^\s*(?:[-*+]\s+|[・●○■□]\s*|\d+[.)]\s+|\d+[．、]\s*)")


def skill_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


# ---------------------------------------------------------------- 入力
def load_items(text: str, csv_mode: bool = False, column: str | None = None) -> list[str]:
    """テキストまたは CSV から項目を取り出す。箇条書きの記号と空行は除く。"""
    if csv_mode:
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []
        header, body = rows[0], rows[1:]
        if column is None:
            idx = 0
        elif column in header:
            idx = header.index(column)
        elif column.isdigit() and int(column) < len(header):
            idx = int(column)
        else:
            raise SystemExit(f"error: 列 '{column}' がない。列名: {header}")
        items = [r[idx] for r in body if len(r) > idx]
    else:
        items = [_BULLET.sub("", line) for line in text.splitlines()]
    return [s.strip() for s in items if s.strip()]


# ---------------------------------------------------------------- 埋め込みとデバイス
def resolve_device(device_pref: str | None = "auto") -> tuple[object, str]:
    """埋め込み計算に使うデバイスを決定する。

    auto のときは利用可能なアクセラレータを優先順に探し、無ければ cpu に落とす。
    対応: cuda (NVIDIA / AMD ROCm), mps (Apple Silicon), xpu (Intel GPU),
          dml / directml (DirectML: Windows), npu (Huawei Ascend),
          hpu (Habana Gaudi), torch.accelerator, cpu

    戻り値: (SentenceTransformer に渡すデバイス, 表示用の名前)
    """
    pref = (device_pref or "auto").strip().lower()

    try:
        import torch
    except ImportError:
        # torch が入っていない環境(テスト等)のフォールバック
        return pref if pref != "auto" else "cpu", pref if pref != "auto" else "cpu"

    if pref in ("dml", "directml"):
        try:
            import torch_directml

            if not torch_directml.is_available():
                raise SystemExit("error: DirectML デバイスが利用できません。")
            return torch_directml.device(), "dml"
        except ImportError:
            try:
                return torch.device("dml"), "dml"
            except Exception:
                raise SystemExit("error: DirectML を利用するには torch-directml が必要です ('pip install torch-directml')。")

    if pref == "auto":
        # 1. CUDA (NVIDIA または AMD ROCm)
        if torch.cuda.is_available():
            idx = torch.cuda.current_device() if hasattr(torch.cuda, "current_device") else 0
            name = f"cuda:{idx}" if torch.cuda.device_count() > 1 else "cuda"
            return name, name
        # 2. Apple Silicon (MPS)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps", "mps"
        # 3. Intel GPU (XPU)
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            idx = torch.xpu.current_device() if hasattr(torch.xpu, "current_device") else 0
            name = f"xpu:{idx}" if torch.xpu.device_count() > 1 else "xpu"
            return name, name
        # 4. DirectML (Windows AMD/Intel GPU 等)
        try:
            import torch_directml

            if torch_directml.is_available():
                return torch_directml.device(), "dml"
        except ImportError:
            pass
        # 5. Huawei Ascend NPU
        if hasattr(torch, "npu") and torch.npu.is_available():
            idx = torch.npu.current_device() if hasattr(torch.npu, "current_device") else 0
            name = f"npu:{idx}" if torch.npu.device_count() > 1 else "npu"
            return name, name
        # 6. Habana Gaudi HPU
        if hasattr(torch, "hpu") and torch.hpu.is_available():
            return "hpu", "hpu"
        # 7. PyTorch 2.4+ torch.accelerator による汎用アクセラレータ
        if hasattr(torch, "accelerator") and torch.accelerator.is_available():
            acc = torch.accelerator.current_accelerator()
            if acc is not None:
                dev_type = acc.type if hasattr(acc, "type") else str(acc)
                return acc, dev_type
        # 8. CPU
        return "cpu", "cpu"

    # 明示指定 (cuda, cuda:0, mps, xpu, npu, cpu 等)
    try:
        dev = torch.device(pref)
    except Exception as e:
        raise SystemExit(f"error: 不正なデバイス指定 '{device_pref}': {e}")
    # 使えないアクセラレータは、モデルの読み込み中に PyTorch の例外で落ちる前に、ここで知らせる
    backend = getattr(torch.backends, "mps", None) if dev.type == "mps" else getattr(torch, dev.type, None)
    is_available = getattr(backend, "is_available", None)
    if dev.type != "cpu" and callable(is_available) and not is_available():
        raise SystemExit(f"error: デバイス '{device_pref}' は利用できません。--device auto か cpu を指定する。")
    display = dev.type if dev.index is None else f"{dev.type}:{dev.index}"
    return pref, display


def embedding_prefix(model: str, override: str | None) -> str:
    """モデルが要求する入力の接頭辞(クラスタリング用)。"""
    if override is not None:
        return override
    name = model.lower()
    if "ruri-v3" in name:
        return "トピック: "
    if "-e5-" in name or "/e5-" in name:
        return "query: "  # E5 は接頭辞が必須。クラスタリングには query を使う
    return ""


def embed(texts: list[str], model: str, prefix: str, device: str = "auto") -> tuple[np.ndarray, str]:
    from sentence_transformers import SentenceTransformer

    dev_target, dev_name = resolve_device(device)
    print(f"embedding {len(texts)} items with {model} on {dev_name}", file=sys.stderr)
    st = SentenceTransformer(model, device=dev_target)
    vecs = st.encode([prefix + t for t in texts], normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float64), dev_name


# ---------------------------------------------------------------- クラスタリング
def cosine_distance(emb: np.ndarray) -> np.ndarray:
    d = np.clip(1.0 - emb @ emb.T, 0.0, None)
    np.fill_diagonal(d, 0.0)
    return d


def silhouette(dist: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """項目ごとの silhouette と、最も近い他グループ(次に入りそうなグループ)を返す。"""
    n, k = len(labels), int(labels.max()) + 1
    counts = np.bincount(labels, minlength=k)
    mean_to = np.stack([dist[:, labels == j].sum(axis=1) / counts[j] for j in range(k)], axis=1)
    rows = np.arange(n)
    size = counts[labels]
    a = mean_to[rows, labels] * size / np.maximum(size - 1, 1)  # 自分自身(距離0)を除いた平均
    other = mean_to.copy()
    other[rows, labels] = np.inf
    neighbor = other.argmin(axis=1)
    b = other[rows, neighbor]
    denom = np.maximum(a, b)
    s = np.where((size > 1) & (denom > 0), (b - a) / np.where(denom > 0, denom, 1.0), 0.0)
    return s, neighbor


def cluster(emb: np.ndarray, k: int, seed: int) -> np.ndarray:
    return KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(emb)


def choose_k(emb: np.ndarray, dist: np.ndarray, k_max: int, seed: int) -> tuple[int, dict[int, float]]:
    """k を 2..k_max で振り、silhouette 平均が最大の k を選ぶ(同点なら小さい k)。"""
    scores = {k: float(silhouette(dist, cluster(emb, k, seed))[0].mean()) for k in range(2, min(k_max, len(emb) - 1) + 1)}
    return max(scores, key=lambda k: (scores[k], -k)), scores


# ---------------------------------------------------------------- キーワード
def make_tokenizer():
    """TF-IDF 用の分割器。SudachiPy で名詞だけを返す。入っていなければ正規表現に落とす。"""
    try:
        from sudachipy import Dictionary, SplitMode

        tok = Dictionary(dict="core").tokenizer(SplitMode.B)
    except ImportError:
        return (lambda text: re.findall(r"\w{2,}", text.lower())), "regex"

    def tokenize(text: str) -> list[str]:
        words = []
        for m in tok.tokenize(text):
            pos = m.part_of_speech()
            if pos[0] != "名詞" or pos[1] in ("数詞", "代名詞", "非自立可能") or pos[2] == "助数詞可能":
                continue  # 数・代名詞・形式名詞・「分」「度」のような助数詞は、グループの特徴にならない
            w = m.normalized_form()
            if not (len(w) == 1 and w.isascii()):
                words.append(w)
        return words

    return tokenize, "sudachi"


def top_terms(texts: list[str], labels: np.ndarray, tokenize, n: int = 8) -> list[list[str]]:
    """グループを1つの文書にまとめて TF-IDF を取り、他のグループより目立つ語を挙げる。"""
    k = int(labels.max()) + 1
    docs = [" ".join(t for t, lab in zip(texts, labels) if lab == c) for c in range(k)]
    try:
        vec = TfidfVectorizer(tokenizer=tokenize, token_pattern=None, sublinear_tf=True)
        x = vec.fit_transform(docs)
    except ValueError:  # 語が1つも取れない
        return [[] for _ in range(k)]
    terms = np.array(vec.get_feature_names_out())
    out = []
    for row in x.toarray():
        top = row.argsort()[::-1][:n]
        out.append([str(terms[i]) for i in top if row[i] > 0])
    return out


# ---------------------------------------------------------------- 結果の組み立て
def build_result(
    texts: list[str],
    emb: np.ndarray,
    k: int | None,
    k_max: int,
    seed: int,
    meta: dict,
    tokenize,
    boundary_limit: int = 5,
) -> dict:
    dist = cosine_distance(emb)
    k_scores = None
    if k is None:
        k, k_scores = choose_k(emb, dist, k_max, seed)
    labels = cluster(emb, k, seed)
    sil, neighbor = silhouette(dist, labels)
    keywords = top_terms(texts, labels, tokenize)

    clusters = []
    for c in range(k):
        idx = np.where(labels == c)[0]
        centroid = emb[idx].mean(axis=0)
        near = idx[np.argsort(-(emb[idx] @ centroid))][:3]
        clusters.append(
            {
                "id": c,
                "size": int(len(idx)),
                "silhouette_mean": round(float(sil[idx].mean()), 4),
                "boundary_count": int((sil[idx] <= 0).sum()),
                "keywords": keywords[c],
                "representatives": [{"index": int(i), "text": texts[i]} for i in near],
            }
        )

    groups: dict[tuple[int, int], list[int]] = {}
    for i in np.where(sil <= 0)[0]:
        groups.setdefault((int(labels[i]), int(neighbor[i])), []).append(int(i))
    boundary_pairs = sorted(
        (
            {
                "from": a,
                "to": b,
                "count": len(v),
                "items": [
                    {"index": i, "text": texts[i], "silhouette": round(float(sil[i]), 4)}
                    for i in sorted(v, key=lambda i: sil[i])[:boundary_limit]
                ],
            }
            for (a, b), v in groups.items()
        ),
        key=lambda p: -p["count"],
    )

    warnings = []
    if k_scores is not None and k == max(k_scores):
        warnings.append(f"自動で選んだ k={k} が探索範囲の上限。k_selection を見て、--k-max を上げるか、目的から k を決める。")
    if k_scores is not None:
        warnings.append(AUTO_K_NOTE)
    if any(c["size"] == 1 for c in clusters):
        warnings.append("1件だけのグループがある。外れ値か、k が大きすぎる可能性がある。")

    return {
        "meta": {
            **meta,
            "n_items": len(texts),
            "k": k,
            "k_selection": None if k_scores is None else {str(kk): round(v, 4) for kk, v in k_scores.items()},
            "silhouette_mean": round(float(sil.mean()), 4),
            "seed": seed,
            "warnings": warnings,
        },
        "clusters": clusters,
        "boundary_pairs": boundary_pairs,
        "items": [
            {
                "index": i,
                "text": texts[i],
                "cluster": int(labels[i]),
                "silhouette": round(float(sil[i]), 4),
                "neighbor_cluster": int(neighbor[i]),
                "boundary": bool(sil[i] <= 0),
            }
            for i in range(len(texts))
        ],
        "limits": LIMITS,
    }


# ---------------------------------------------------------------- CLI
def main() -> None:
    p = argparse.ArgumentParser(description="項目の集合をクラスタリングし、MECE の判断材料を JSON で出す")
    p.add_argument("--version", action="version", version=f"mece-cluster-advisor {skill_version()}")
    p.add_argument("input", help="入力ファイル(.csv は1行目をヘッダとして扱う)。標準入力は -")
    p.add_argument("--column", help="CSV の列名または0始まりの列番号(既定: 先頭列)")
    p.add_argument("--k", default="auto", help="グループ数。auto は silhouette で選ぶ(既定)")
    p.add_argument("--k-max", type=int, default=8, help="auto で試す k の上限(既定 8)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"埋め込みモデル(既定 {DEFAULT_MODEL})")
    p.add_argument("--prefix", help="入力の接頭辞。省略するとモデル名から決める")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--device",
        default="auto",
        help="計算デバイス(既定 auto: 利用可能な GPU/アクセラレータを自動選択。cuda, mps, xpu, dml, npu, cpu 等)",
    )
    p.add_argument("--out", help="JSON の保存先。省略すると標準出力")
    args = p.parse_args()

    raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
    texts = load_items(raw, csv_mode=args.input.lower().endswith(".csv"), column=args.column)
    if len(texts) < MIN_ITEMS:
        raise SystemExit(f"error: 項目が少なすぎる({len(texts)}件)。{MIN_ITEMS}件以上が必要。")
    k = None if args.k == "auto" else int(args.k)
    if k is not None and not 2 <= k <= len(texts) - 1:
        raise SystemExit(f"error: --k は 2 以上 {len(texts) - 1} 以下にする。")

    prefix = embedding_prefix(args.model, args.prefix)
    tokenize, tok_name = make_tokenizer()
    emb, dev_name = embed(texts, args.model, prefix, device=args.device)
    result = build_result(
        texts,
        emb,
        k,
        args.k_max,
        args.seed,
        {"model": args.model, "prefix": prefix, "tokenizer": tok_name, "device": dev_name},
        tokenize,
    )

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"saved: {args.out}", file=sys.stderr)
    else:
        print(out)


if __name__ == "__main__":
    main()
