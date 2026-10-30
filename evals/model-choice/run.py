#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""SKILL.md の「モデルの選び方」の目安を、小さな比較で確かめる。

目安: 「グループの命名は軽量なモデルでも足りる。排他性の判定と網羅性の指摘は、推論力の高いモデルのほうが向く」。

    uv run evals/model-choice/run.py                     # 3 モデル × 3 場面 × 3 回(claude -p を順に呼ぶ)
    uv run evals/model-choice/run.py --repeats 1 --models claude-haiku-5-5   # 動作確認

場面(項目は同じフォルダの txt):
  overlap.txt  分類案に、重なる 2 つのカテゴリ(画面の操作性 / 使い方の分かりにくさ)を仕込んである
  gap.txt      目的が求める観点のうち、職場の人間関係の項目が 1 件も無い
  clean.txt    分類案は目的に合っている(重なりや抜けを構造的な問題として指摘したら、誤検出)

各モデルは、道具(scripts/mece_cluster.py)の出力と項目、目的、分類案を渡されて、命名・排他性・網羅性・結論を答える。
回答は、固定の採点役(--grader)が、仕込んだ事実に対する是非の問いに答える形で採点する。
採点役も LLM なので、採点の誤りは残る。回答の全文は feedback/model-choice/ に保存し、後から読み直せる。
モデルの呼び出しは、利用者の Claude Code の契約を使う(設定・フック・ツールは読み込まない)。結果は feedback/model-choice/ に置く(Git の対象外)。
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "feedback" / "model-choice"

SCENARIOS = {
    "overlap": {
        "k": 4,
        "purpose": "社内システムへの不満を、改善の担当を決めるために分けたい。",
        "scheme": "①認証・ログイン ②動作の遅さ ③画面の操作性 ④使い方の分かりにくさ",
        "questions": {
            "flagged": "回答は、「画面の操作性」と「使い方の分かりにくさ」が重なる(どちらにも入りうる項目がある、または区別が曖昧である)ことを、問題として指摘していますか。",
            "wrong_alarm": "回答は、「認証・ログイン」と「動作の遅さ」の間に、構造的な重なりがあると指摘していますか。",
        },
    },
    "gap": {
        "k": 3,
        "purpose": "新入社員が配属後 3 か月で困ることを、漏れなく把握したい。把握したい観点は、業務知識、ツールの操作、職場の人間関係、生活・健康の 4 つ。",
        "scheme": "①業務知識 ②ツールの操作 ③生活・健康",
        "questions": {
            "flagged": "回答は、「職場の人間関係」の観点が、項目にも分類案にも無い(抜けている)ことを、指摘していますか。",
            "wrong_alarm": "回答は、「業務知識」「ツールの操作」「生活・健康」のカテゴリどうしが重なっていると、構造的な問題として指摘していますか。",
        },
    },
    "clean": {
        "k": 4,
        "purpose": "ネット通販への不満を、対応する部署を決めるために分けたい。",
        "scheme": "①配送 ②価格 ③問い合わせ対応 ④商品情報",
        "questions": {
            "flagged": "回答は、分類案に構造的な重なり、または目的に対する大きな抜けがあるとして、「そのままでは使えない」と結論していますか。個別の項目が境界にあるという注意だけなら「いいえ」です。",
            "wrong_alarm": "回答の結論は「いいえ」(使えない)ですか。「はい」または「条件つき」なら「いいえ」です。",
        },
    },
}
NAMING_Q = "回答の「グループごとの名前案」は、道具の出力に示されたそのグループの代表項目・キーワードの内容に合っていますか。3 =すべて合っている、2 =一部ずれている、1 =多くが合っていない、0 =名前案が無い。"


def tool_output(name: str, k: int) -> dict:
    """道具(scripts/mece_cluster.py)の出力。1 度作れば再利用する。"""
    digest = hashlib.sha1(((HERE / f"{name}.txt").read_bytes() + str(k).encode())).hexdigest()[:8]  # 項目か k が変われば作り直す
    path = OUT / f"tool-{name}-{digest}.json"
    if not path.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uv", "run", str(ROOT / "scripts" / "mece_cluster.py"), str(HERE / f"{name}.txt"), "--k", str(k), "--out", str(path)],
                       check=True, cwd=ROOT)
    return json.loads(path.read_text(encoding="utf-8"))


def prompt_for(name: str, sc: dict) -> str:
    r = tool_output(name, sc["k"])
    clusters = [{k: c[k] for k in ("id", "size", "keywords", "representatives") if k in c} for c in r["clusters"]]
    items = (HERE / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    return f"""次は、項目の集合を埋め込みとクラスタリングで分けた結果(道具の出力)、利用者の目的、利用者の分類案である。
道具は意味の近さしか測れない。軸が 1 つか、目的に対して全体を覆っているかは測れないので、あなたが判断する。

【目的】{sc["purpose"]}
【利用者の分類案】{sc["scheme"]}
【道具の出力】
グループ: {json.dumps(clusters, ensure_ascii=False)}
境界にある項目の組: {json.dumps(r["boundary_pairs"], ensure_ascii=False)}
【全項目】
""" + "\n".join(f"{i}. {t}" for i, t in enumerate(items)) + """

次を日本語で答える。
1. 道具のグループ(id ごと)の名前案
2. 排他性: 分類案の中で、重なる・どちらにも入りうるカテゴリの組と、その根拠にした項目
3. 網羅性: 目的に照らして、抜けている観点
4. 結論: この分類案をそのまま使ってよいか(はい / いいえ / 条件つき)と、直すべき点"""


def claude(prompt: str, model: str, system: str) -> tuple[str, float]:
    t0 = time.time()
    p = subprocess.run(
        ["env", "-u", "CLAUDECODE", "claude", "-p", prompt, "--model", model, "--setting-sources", "", "--tools", "",
         "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence", "--system-prompt", system, "--output-format", "text"],
        capture_output=True, text=True, cwd="/tmp", stdin=subprocess.DEVNULL,
    )
    if p.returncode != 0 or not p.stdout.strip():
        raise SystemExit(f"error: claude -p が失敗した({model}): {p.stderr[:300]}")
    return p.stdout.strip(), time.time() - t0


def grade(answer: str, sc: dict, grader: str, name: str) -> dict:
    qs = {**sc["questions"], "naming": NAMING_Q}
    r = tool_output(name, sc["k"])
    clusters = [{k: c[k] for k in ("id", "size", "keywords", "representatives") if k in c} for c in r["clusters"]]
    ask = ("次の【回答】について、各問いに答える。回答に書かれていることだけで判断し、書かれていないことを補わない。\n"
           "出力は JSON だけ。キーは問いの名前、値は true / false(naming だけは 0〜3 の整数)にする。\n\n"
           "【道具の出力(グループの代表項目とキーワード。naming の判断に使う)】\n" + json.dumps(clusters, ensure_ascii=False) + "\n\n【回答】\n" + answer + "\n\n【問い】\n"
           + "\n".join(f"- {k}: {q}" for k, q in qs.items()))
    out, _ = claude(ask, grader, "あなたは採点役である。JSON だけを出力する。")
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise SystemExit(f"error: 採点の出力が JSON でない: {out[:200]}")
    return json.loads(m.group(0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"])
    ap.add_argument("--grader", default="claude-sonnet-5-5")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--scenarios", nargs="+", default=list(SCENARIOS))
    ap.add_argument("--regrade", action="store_true", help="保存した回答(answer-*.txt)を、モデルを呼ばずに採点し直す")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    system = "あなたは日本語で答える、分類の設計を助けるアシスタントである。"
    records = []
    for name in args.scenarios:
        sc = SCENARIOS[name]
        prompt = prompt_for(name, sc)
        for model in args.models:
            for rep in range(args.repeats):
                saved = OUT / f"answer-{name}-{model}-{rep}.txt"
                if args.regrade:
                    ans, sec = saved.read_text(encoding="utf-8"), 0.0
                else:
                    ans, sec = claude(prompt, model, system)
                    saved.write_text(ans, encoding="utf-8")
                g = grade(ans, sc, args.grader, name)
                records.append({"scenario": name, "model": model, "rep": rep, "sec": round(sec, 1), "chars": len(ans), **g})
                print(records[-1], file=sys.stderr, flush=True)
    (OUT / ("records-regrade.json" if args.regrade else "records.json")).write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"採点役: {args.grader}。各セルは {args.repeats} 回の合計(真の数/回数)。")
    print(f"{'場面':<9}{'モデル':<20}{'仕込んだ問題を指摘':>18}{'誤検出':>8}{'命名(0-3)':>11}{'秒':>7}")
    for name in args.scenarios:
        for model in args.models:
            rs = [r for r in records if r["scenario"] == name and r["model"] == model]
            flagged = sum(bool(r["flagged"]) for r in rs)
            wrong = sum(bool(r["wrong_alarm"]) for r in rs)
            naming = sum(int(r["naming"]) for r in rs) / len(rs)
            print(f"{name:<9}{model:<20}{f'{flagged}/{len(rs)}':>18}{f'{wrong}/{len(rs)}':>8}{naming:>11.1f}{sum(r['sec'] for r in rs) / len(rs):>7.0f}")
    print("(overlap・gap は『仕込んだ問題を指摘』が多いほど良い。clean は『仕込んだ問題を指摘』が誤検出の意味になり、少ないほど良い)")


if __name__ == "__main__":
    main()
