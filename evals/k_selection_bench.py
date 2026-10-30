# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2.5.4",
#     "scikit-learn>=1.9.1",
#     "sentence-transformers>=6.2.0",
#     "torch>=2.15.0",
#     "pyarrow",
# ]
# ///
"""k の選び方(自動)が、話題の数に追従するかを測る。

    uv run evals/k_selection_bench.py

livedoor ニュースの 9 カテゴリから、m = 3・5・7・9 個のカテゴリを選んだ部分集合を作る。
正解の話題数は m である。各基準が選ぶ k が m に近いか、その k での ARI が高いかを比べる。
埋め込みと取得したデータは evals/dr_bench.py と共有する(feedback/dr-bench/)。
"""

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, calinski_harabasz_score, davies_bouldin_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dr_bench  # noqa: E402
from mece_cluster import cosine_distance, silhouette  # noqa: E402

warnings.filterwarnings("ignore")
K_RANGE = range(2, 13)


def criteria(emb: np.ndarray, dist: np.ndarray, labs: dict[int, np.ndarray]) -> dict[str, int]:
    sil = {k: float(silhouette(dist, labs[k])[0].mean()) for k in K_RANGE}
    ch = {k: calinski_harabasz_score(emb, labs[k]) for k in K_RANGE}
    db = {k: davies_bouldin_score(emb, labs[k]) for k in K_RANGE}
    top = max(sil.values())
    return {
        "silhouette(現行)": max(sil, key=lambda k: (sil[k], -k)),
        "Calinski-Harabasz": max(ch, key=lambda k: (ch[k], -k)),
        "Davies-Bouldin": min(db, key=lambda k: (db[k], k)),
        "silhouette 最大-0.01 以内で最大の k": max(k for k in K_RANGE if sil[k] >= top - 0.01),
        "silhouette 最大-0.02 以内で最大の k": max(k for k in K_RANGE if sil[k] >= top - 0.02),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", nargs="+", default=["title", "lead"])
    ap.add_argument("--subs", nargs="+", type=int, default=[0, 1])
    ap.add_argument("--ms", nargs="+", type=int, default=[3, 5, 7, 9], help="正解の話題数")
    ap.add_argument("--subsets", type=int, default=4, help="m ごとのカテゴリの選び方の数")
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1])
    args = ap.parse_args()

    rows = dr_bench.load_rows()
    dr_bench.ensure_embeddings(rows, args.settings, args.subs)
    results = []  # (setting, m, criterion, k, ari)
    for setting in args.settings:
        for sub in args.subs:
            emb_all, y_all = dr_bench.get_emb(rows, setting, sub, embed_ok=False)
            cats = sorted(set(y_all))
            bad = [m for m in args.ms if not 2 <= m <= len(cats)]
            if bad:  # m がカテゴリ数を超えると、正解の数と実際の部分集合が食い違った表になる
                raise SystemExit(f"error: --ms は 2 以上 {len(cats)} 以下にする: {bad}")
            for m in args.ms:
                rng = np.random.default_rng(7 + m)
                for _ in range(args.subsets):
                    chosen = set(rng.choice(cats, m, replace=False)) if m < len(cats) else set(cats)
                    mask = np.array([c in chosen for c in y_all])
                    emb, y = emb_all[mask], np.unique(y_all[mask], return_inverse=True)[1]
                    dist = cosine_distance(emb)
                    for seed in args.seeds:
                        labs = {k: KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(emb) for k in K_RANGE}
                        ari = {k: adjusted_rand_score(y, labs[k]) for k in K_RANGE}
                        for name, k in criteria(emb, dist, labs).items():
                            results.append((setting, m, name, k, ari[k], max(ari, key=ari.get)))

    names = list(dict.fromkeys(r[2] for r in results))
    for setting in args.settings:
        print(f"\n## {setting}  (選ばれた k の平均 / 正解 m との絶対差の平均 / その k での ARI の平均)")
        print(f"{'基準':<34}" + "".join(f"{'m=' + str(m):>20}" for m in args.ms) + f"{'全体の|k-m|':>14}{'全体のARI':>11}")
        for name in names:
            cells, diffs, aris = [], [], []
            for m in args.ms:
                rs = [r for r in results if r[0] == setting and r[1] == m and r[2] == name]
                ks, ar = [r[3] for r in rs], [r[4] for r in rs]
                cells.append(f"{np.mean(ks):>6.1f} /{np.mean(np.abs(np.array(ks) - m)):>4.1f} /{np.mean(ar):>5.2f}")
                diffs += list(np.abs(np.array(ks) - m))
                aris += ar
            print(f"{name:<34}" + "".join(f"{c:>20}" for c in cells) + f"{np.mean(diffs):>14.2f}{np.mean(aris):>11.3f}")
        best = [np.mean([r[4] for r in results if r[0] == setting and r[2] == names[0] and r[1] == m]) for m in args.ms]
        oracle = [np.mean([r[5] for r in results if r[0] == setting and r[2] == names[0] and r[1] == m]) for m in args.ms]
        print(f"(参考) ARI が最大になる k の平均: " + ", ".join(f"m={m}: {o:.1f}" for m, o in zip(args.ms, oracle)))


if __name__ == "__main__":
    main()
