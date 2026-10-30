# MECE Cluster Advisor

項目の集合(アイデア、要件、顧客の声、記事タイトル、論点など)を、MECE(漏れなく重複なく)に分類・整理するための判断材料を作る、Claude Code と Codex 向けのスキルである。`install.py` は、この2つへインストールする。

分割を自動で確定する道具ではない。埋め込みとクラスタリングで、グループ候補、境界にある曖昧な項目、重複しやすいグループの組を出す。軸の命名、排他性の判定、網羅性の穴の指摘は、ホストのモデルが行い、最終判断は利用者に残す。

MECE は目的と軸で決まる。同じ項目でも、目的が変われば正しい分け方も変わる。埋め込みが測れるのは意味の近さだけである。「軸が1つか」と「全体を覆っているか」は測れない。そのため、この2点はモデルと利用者が判断する、という分担にしている。

具体的な操作手順は [docs/usage.md](docs/usage.md) にある。

## 担当の分け方

| 担当 | 内容 |
|---|---|
| `scripts/mece_cluster.py`(決定的) | 埋め込み、グループ分け、境界の項目、キーワード、代表項目 |
| ホストのモデル | グループの命名と定義、軸の確認、排他性の判定、網羅性の穴の指摘 |
| 利用者 | 目的と軸の確定、最終的な分割の決定 |

LLM は呼ばない。項目のテキストは外部へ送らない。通信は、初回のモデル取得と更新確認のときだけである。

## 構成

### スキル本体と実行

| パス | 内容 |
|---|---|
| `SKILL.md` | スキル本体。手順、件数による分岐、報告の形 |
| `references/judgment.md` | 4つの判断(命名、軸、排他性、網羅性)の手順と設計の根拠 |
| `references/output-schema.md` | 出力 JSON の項目、指標の意味、読み方 |
| `scripts/mece_cluster.py` | クラスタリング本体(依存はスクリプト内の PEP 723 ブロック) |
| `scripts/test_mece_cluster.py` | モデルを使わない確認(合成した埋め込みで動く) |
| `scripts/skill_info.py` | 版と実行環境(OS・アプリ・モデル・日付)を出す。標準ライブラリだけ、読み取り専用 |
| `scripts/test_skill_info.py` | `skill_info.py` の確認 |
| `install.py` | インストール(更新)、実行時の前提(uv とモデル)の取得、アンインストール |

### リリースと CI

| パス | 内容 |
|---|---|
| `VERSION` | スキルの版。`main` で変わると、Actions がタグと Release を作る |
| `.github/workflows/release.yml` | `VERSION` が変わったときに、タグ・zip・sha256・Release を作る |
| `docs/release-notes/` | リリースごとのノート(`v<版>.md`)。版を上げる PR に入れる |
| `.github/workflows/ci.yml` | `install.py` を Linux と Windows で動かす確認 |
| `.github/workflows/real-model.yml` | 実モデルを Linux・Windows で動かす手動の検査 |

### 文書

| パス | 内容 |
|---|---|
| `docs/usage.md` | 操作方法の詳細(インストール、オプション、結果の読み方) |
| `docs/dimensionality-reduction.md` | 次元削減(PCA / UMAP / PaCMAP / t-SNE)の評価結果と、入れない理由 |
| `docs/k-selection.md` | 自動で選ぶ k の評価結果と、警告を出す理由 |
| `docs/model-choice.md` | モデルの選び方の評価結果 |

### 評価(`evals/`)

| パス | 内容 |
|---|---|
| `README.md`、`trigger-eval*.json` | 発動精度の評価セットと、その読み方 |
| `smoke-items.txt` | 実モデルの確認に使う17件(`real-model.yml` と、`docs/usage.md` の確認表) |
| `dr_bench.py`、`dr_extend.py` | 次元削減の評価の再現スクリプト。`dr_extend.py` は、件数・モデル・口語の短文・t-SNE の調整へ広げたもの |
| `k_selection_bench.py` | 自動で選ぶ k の評価の再現スクリプト |
| `model-choice/` | モデルの選び方の目安を確かめる比較(項目と実行スクリプト) |

## インストール

スキルとしてコピーする。リポジトリ直下で実行する。

```bash
uv run install.py
```

- Claude Code は `~/.claude/skills/`、Codex は `~/.agents/skills/` を見る。
- 再実行すると更新になる。
- 対象の絞り込み、取得の省略、削除、キャッシュの削除は、[docs/usage.md](docs/usage.md) の「インストール」にある。

## 使い方

スキルとして使うときは、次のように依頼する。

- 「MECEに分けて」
- 「分類の切り口を提案して」
- 「大量のコメントをグルーピングして」
- 「カテゴリの重複や抜け漏れを確認して」

30件前後までならモデルが直接分けるので、スクリプトは使わない(`SKILL.md` の「スクリプトを使わないとき」)。

スクリプトを直接実行するときは、次のとおり。

```bash
uv run scripts/mece_cluster.py items.txt --out result.json
uv run scripts/mece_cluster.py items.csv --column comment --k 5
```

入力の形式、オプション、初回の取得、計算デバイスの指定は、[docs/usage.md](docs/usage.md) の「スクリプトを直接使う」にある。

## 出力

JSON を出す。次の順に読む。

1. `meta.warnings`
2. `meta.k` と `meta.k_selection`
3. `clusters`
4. `boundary_pairs`
5. 必要な分だけ `items`

項目が100件を超えるときは、`items` を全部読まない。

silhouette に合格ラインはない。正解が分かっている3テーマ18件を k=3 で完全に分けても、平均は 0.18 だった。同じデータで k を変えたときの比較に使う。

指標の意味と実例は [references/output-schema.md](references/output-schema.md) にある。

## 確認と評価

```bash
uv run scripts/test_mece_cluster.py   # モデル不要
python3 scripts/test_skill_info.py    # 版と実行環境の出力
```

`install.py` は、GitHub Actions で Linux(ubuntu-latest)と Windows(windows-latest)の両方で確かめている。確かめる内容は [docs/usage.md](docs/usage.md) の「確認」にある。

評価の入口は次のとおり。

- `SKILL.md` の description が発動するか: [evals/README.md](evals/README.md)(実行方法、照合の修正、2026-10-12 の測定結果)
- 次元削減を入れない理由: [docs/dimensionality-reduction.md](docs/dimensionality-reduction.md)
- 自動で選ぶ k の評価: [docs/k-selection.md](docs/k-selection.md)
- モデルの選び方の評価: [docs/model-choice.md](docs/model-choice.md)

## ライセンス

MIT。[LICENSE](LICENSE) を見る。
