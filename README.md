# MECE Cluster Advisor

項目の集合(アイデア、要件、顧客の声、記事タイトル、論点など)を MECE(漏れなく重複なく)に分類・整理するときの判断材料を作る、Claude Code / Codex / Gemini CLI 向けのスキルである。

分割を自動で確定する道具ではない。埋め込みとクラスタリングで、グループ候補、境界にある曖昧な項目、重複しやすいグループの組を出す。軸の命名、排他性の判定、網羅性の穴の指摘は、ホストのモデルが行い、最終判断は利用者に残す。

MECE は目的と軸で決まる。同じ項目でも、目的が変われば正しい分け方が変わる。埋め込みが測れるのは意味の近さだけで、「軸が1つか」と「全体を覆っているか」は測れない。この2点をモデルと利用者が判断する、という分担にしている。

## 担当の分け方

| 担当 | 内容 |
|---|---|
| `scripts/mece_cluster.py`(決定的) | 埋め込み、グループ分け、境界の項目、キーワード、代表項目 |
| ホストのモデル | グループの命名と定義、軸の確認、排他性の判定、網羅性の穴の指摘 |
| 利用者 | 目的と軸の確定、最終的な分割の決定 |

LLM は呼ばない。項目のテキストは外部へ送らない。通信するのは、初回のモデル取得と更新確認だけである。

## 構成

| パス | 内容 |
|---|---|
| `SKILL.md` | スキル本体。手順、件数による分岐、報告の形 |
| `references/judgment.md` | 4つの判断(命名、軸、排他性、網羅性)の手順と設計の根拠 |
| `references/output-schema.md` | 出力 JSON の項目、指標の意味、読み方 |
| `scripts/mece_cluster.py` | クラスタリング本体(依存はスクリプト内の PEP 723 ブロック) |
| `scripts/test_mece_cluster.py` | モデルを使わない確認(合成した埋め込みで動く) |
| `evals/` | 発動精度の評価セットと、その読み方 |

## インストール

スキルとして置く。Claude Code は `~/.claude/skills/`、Codex は `~/.agents/skills/` を見る。リポジトリ直下で実行する(`--delete` を使うため)。

```bash
rsync -a --delete --exclude .git --exclude .gitignore --exclude .claude --exclude .DS_Store --exclude __pycache__ ./ ~/.claude/skills/mece-cluster-advisor/
rsync -a --delete --exclude .git --exclude .gitignore --exclude .claude --exclude .DS_Store --exclude __pycache__ ./ ~/.agents/skills/mece-cluster-advisor/
```

`.claude/` は実行環境の設定(トークンを含む)、`__pycache__/` はキャッシュなので、同期しない。

Codex はスキル一覧で description を短く切るので、発動は弱くなる(未検証)。

## 使い方

スキルとして使うときは、「MECEに分けて」「分類の切り口を提案して」「大量のコメントをグルーピングして」「カテゴリの重複や抜け漏れを確認して」のように依頼する。30件前後までならモデルが直接分けるので、スクリプトは使わない(`SKILL.md` の「スクリプトを使わないとき」)。

スクリプトを直接叩くときは、次のとおり。

```bash
uv run scripts/mece_cluster.py items.txt --out result.json
uv run scripts/mece_cluster.py items.csv --column comment --k 5
```

入力は、1行1項目のテキストか、1行目をヘッダとする CSV(`.csv` の拡張子で判定)。標準入力は `-`。

| 指定 | 内容 |
|---|---|
| `--column` | CSV の列名または0始まりの列番号(既定: 先頭列) |
| `--k` | グループ数。`auto`(既定)は silhouette が最大の k |
| `--k-max` | `auto` で試す k の上限(既定 8) |
| `--model` / `--prefix` | 埋め込みモデルと入力の接頭辞(既定 `cl-nagoya/ruri-v3-310m`、接頭辞はモデル名から決める) |
| `--seed` | 乱数の種(既定 42)。同じ入力と設定なら同じ結果になる |
| `--out` | JSON の保存先。省略すると標準出力 |

実行には `uv` と Python 3.12 以上が要る。初回は埋め込みモデル(約1.2GB)とライブラリを取得する。macOS(arm64)での実測で、Linux の CUDA 版 torch ではさらに増える。2回目以降はキャッシュを使う。

## 出力

JSON を出す。読む順は `meta.warnings` → `meta.k` と `meta.k_selection` → `clusters` → `boundary_pairs` → 必要な分だけ `items` である。指標の意味と実例は [references/output-schema.md](references/output-schema.md) にある。

項目が100件を超えるときは `items` を全部読まない。

silhouette に合格ラインはない。正解が分かっている3テーマ18件を k=3 で完全に分けても、平均は 0.18 だった。同じデータで k を変えたときの比較に使う。

## 確認と評価

```bash
uv run scripts/test_mece_cluster.py   # モデル不要
```

`SKILL.md` の description が発動するかの評価セットは [evals/](evals/) にある。実行方法、照合の修正、2026-10-12 の測定結果は [evals/README.md](evals/README.md) を見る。

## ライセンス

MIT。[LICENSE](LICENSE) を見る。
