# 発動精度の評価セット

`SKILL.md` の description が、このスキルを使うべき依頼で発動するかを測るクエリ集である。形式は `{query, should_trigger}` の配列で、skill-creator の `run_eval.py` にそのまま渡せる。

| ファイル | 件数 | 内容 |
|---|---|---|
| `trigger-eval.json` | 24(肯定12、否定12) | データを添えない依頼 |
| `trigger-eval-data.json` | 3(肯定3) | 肯定の依頼に、実際の項目を本文へ展開したもの |
| `trigger-eval-data9.json` | 9(肯定9) | 同上。`trigger-eval.json` の肯定側を展開したもの |

肯定側は「30件以上あって、MECE に分けたい・重複や抜けを確かめたい」依頼である。否定側は、近いが別の領域の依頼を置いている。文章の推敲、表の集計、MECE の説明、コードの修正、3案の比較、議事録の要約、タイトル案の生成である。

## 実行

skill-creator の `run_eval.py` を使う。プラグインの場所は環境によって違う(`~/.claude/plugins/marketplaces/claude-plugins-official/plugins/skill-creator/skills/skill-creator/scripts/run_eval.py` など)。

スキルのフォルダの外、中立のディレクトリから実行する。このスクリプトは、cwd から上へ `.claude/` を探し、見つけた場所に一時的なコマンドファイルを作る。

```bash
python3 /path/to/run_eval_patched.py \
  --eval-set /path/to/mece-cluster-advisor/evals/trigger-eval.json \
  --skill-path ~/.claude/skills/mece-cluster-advisor \
  --num-workers 1
```

注意点が2つある。どちらも「発動しなかった」という偽の結果を生む。

### 1. 照合の修正が要る

`run_eval.py` は、一時的なコマンド名(`<skill>-skill-<id>`)を含む呼び出しだけを発動と数える。このスキルが `~/.claude/skills/` に入っていると、モデルは `Skill {"skill": "mece-cluster-advisor"}` を呼ぶので、当たらない。

プラグインのファイルは更新で上書きされるので、コピーを作ってから、3か所を直す。

```diff
--- run_eval.py
+++ run_eval_patched.py
@@ -144,11 +144,11 @@
                             delta = se.get("delta", {})
                             if delta.get("type") == "input_json_delta":
                                 accumulated_json += delta.get("partial_json", "")
-                                if clean_name in accumulated_json:
+                                if (pending_tool_name == 'Skill' and skill_name in accumulated_json) or clean_name in accumulated_json:
                                     return True
 
                         elif se_type in ("content_block_stop", "message_stop"):
                             if pending_tool_name:
-                                return clean_name in accumulated_json
+                                return (pending_tool_name == 'Skill' and skill_name in accumulated_json) or clean_name in accumulated_json
                             if se_type == "message_stop":
                                 return False
@@ -161,7 +161,7 @@
-                            if tool_name == "Skill" and clean_name in tool_input.get("skill", ""):
+                            if tool_name == "Skill" and (clean_name in tool_input.get("skill", "") or tool_input.get("skill", "") == skill_name):
                                 triggered = True
                             elif tool_name == "Read" and clean_name in tool_input.get("file_path", ""):
                                 triggered = True
```

`skill_name` は既にある引数なので、他は直さなくてよい。

### 2. 項目を本文に入れる

「35個のアイデアを貼ります」「そのデータはこちら」のように、項目が本文にない依頼だと、モデルは `ls` やデータの要求を先に出す。発動の判定にならない。項目を本文に入れたのが `trigger-eval-data*.json` である。

`--num-workers` の既定は10だが、負荷で結果がぶれることがある。疑わしいときは1にする。

## 2026-10-12 の測定結果

Claude Code の `claude -p`、`--runs-per-query 3`、上のパッチを当てた `run_eval.py`、`--num-workers 1` で測った。

| 評価セット | 結果 |
|---|---|
| `trigger-eval.json` | 21/24 通過(発動 27/72回) |
| `trigger-eval-data.json` | 3/3 通過(発動 15/15回) |
| `trigger-eval-data9.json` | 6/9 通過(発動 20/27回) |

- パッチ前の初回は 0/60 で、全件が発動しなかった。原因は照合の不一致である。description の問題ではない。
- `trigger-eval.json` で落ちた3件は、項目を本文に入れる(`trigger-eval-data.json`)と、3回とも発動した。
- `trigger-eval-data9.json` では、項目を入れても落ちるものがある。問い合わせ件名200件、会議の意見50件、論点60件の章立てである。原因は特定していない(モデルが自分で分けてしまった可能性がある)。
- 否定側12件は、どの実行でも発動しなかった(誤発動0)。

## 注意

- この評価セットは Claude が下書きしたもので、利用者の確認を受けていない。
- 1件あたり3回の実行でも、件数が少ないので数値はぶれる。差をそのまま結論にしない。
- 元の測定は、このリポジトリの外(セッションの scratchpad)で行った。生の結果 JSON と実行ログはそこにあり、このリポジトリには数値だけを残している。
