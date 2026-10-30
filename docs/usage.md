# 操作方法

このファイルは、[README.md](../README.md) の概要を、実際の操作手順にしたものである。コマンドはすべてリポジトリ直下で実行する。

## 目次

- [必要な環境](#必要な環境)
- [インストール](#インストール)
- [スキルとして使う](#スキルとして使う)
- [スクリプトを直接使う](#スクリプトを直接使う)
- [結果を読む](#結果を読む)
- [版と実行環境](#版と実行環境)
- [確認](#確認)

## 必要な環境

| 項目 | 内容 |
|---|---|
| `uv` | 無ければ `install.py` が公式インストーラで入れる |
| Python | 3.12 以上(スクリプトを実行するとき) |
| ディスク | 初回の取得で、埋め込みモデルと依存をダウンロードする |
| 通信 | 初回の取得と更新確認に必要。以降はオフラインでも動く |

## インストール

### 基本

```bash
uv run install.py
```

Claude Code は `~/.claude/skills/`、Codex は `~/.agents/skills/` にコピーされる。再実行すると更新になる。

### オプション

| オプション | 動作 |
|---|---|
| (なし) | Claude Code と Codex の両方へインストールする |
| `--target claude` | Claude Code のみ |
| `--target codex` | Codex のみ |
| `--no-fetch` | 依存とモデルの取得をしない |
| `--uninstall` | 両方から削除する |
| `--purge` | 削除し、取得したモデルと依存のキャッシュも消す |

```bash
uv run install.py --target claude
uv run install.py --no-fetch
uv run install.py --uninstall
uv run install.py --purge
```

### uv がないとき

`uv run install.py` は、Mac と Windows で同じコマンドである。`uv` が無ければ、次のコマンドでもよい。

```bash
python3 install.py
```

Windows では `python install.py` を使う。

### インストールが行うこと

| 前提 | `install.py` の動作 |
|---|---|
| `uv` が PATH にある | 無ければ公式インストーラで入れる(`~/.local/bin/`) |
| 依存と埋め込みモデル | 4件の仮の入力を実際に流し、取得と動作を確かめる(モデルは約1.2GB。macOS arm64 での実測。Linux では CUDA 版 torch などで増えることがある) |
| 通信できること | 取得はここで済む。以降は `HF_HUB_OFFLINE=1` でも動く |

`--no-fetch` で取得を後回しにしたときは、最初の実行時に取得と了承が要る(`SKILL.md` の手順3)。

### 更新

`git pull` してから、同じコマンドをもう一度実行する。リポジトリから消えたファイルは、インストール先からも消える。

### コピーされないもの

- Git の作業ツリー(リポジトリ直下)から実行したとき: Git が追跡しているファイルだけをコピーする。未追跡のファイル(`.env`、`CLAUDE.local.md`、メモなど、名前によらない)は入らない。さらに、追跡していても `.git`、`.gitignore`、`.claude/`、`.codex/`、`.serena/`、`.venv/`、`feedback/`、`__pycache__/`、`*.local.md` は入れない。
- Release の zip の展開先など、Git の管理外から実行したとき: 上の名前のものを除いて、すべてコピーする。zip には追跡しているファイルしか入っていないので、結果は同じになる。
- `.git` があるのに `git` が使えないときは、名前の除外に戻さず、止まる。`git` を入れるか、zip から入れる。

### `--purge` が消すもの

- モデルのキャッシュ:`~/.cache/huggingface/hub/`。`HF_HOME` か `HF_HUB_CACHE` を設定していれば、そこ。
- このスキルのスクリプト用に uv が作った実行環境のキャッシュ:`uv cache dir` の下。実測で約1.5GB。

次は消えない。

- 展開済みのパッケージ:他のプロジェクトと共有しているため。

これも消したいときは、次を使い分ける。

- `uv cache clean`:キャッシュを全消しする。
- `uv cache prune`:未使用の分だけ消す。

### Codex の注意

Codex は、スキル一覧の description を、スキルの数に応じて切る。スキルが多い環境では、前方の十数文字しか残らない。この Mac(Codex 0.164.0、スキル 200 件超)では、このスキルは `項目の集合(アイデア、要件、` までしか見えなかった。

`evals/trigger-eval.json` の 24 件を `codex exec` で流した結果は、肯定 12 件のうち 10 件で発動し、否定 12 件では発動しなかった。外れたのは、「MECE」と書かれていない依頼(問い合わせ件名の分類の切り口の提案、タイトル案のグルーピング)だった。名前と依頼文の語に頼って発動しているので、スキルが多い環境では、依頼に「MECE」「分類」などを入れると確実になる。description を直す件は #36 にある。

## スキルとして使う

Claude Code や Codex で、次のように依頼する。

- 「MECEに分けて」
- 「分類の切り口を提案して」
- 「大量のコメントをグルーピングして」
- 「カテゴリの重複や抜け漏れを確認して」

30件前後までならモデルが直接分けるので、スクリプトは使わない(`SKILL.md` の「スクリプトを使わないとき」)。

## スクリプトを直接使う

### 入力

| 形式 | 扱い |
|---|---|
| `.csv` | 1行目をヘッダとして扱う。`--column` で列を選ぶ |
| それ以外 | 1行1項目のテキストとして扱う |
| 標準入力 | `-` を指定する |

### 実行例

```bash
uv run scripts/mece_cluster.py items.txt --out result.json
uv run scripts/mece_cluster.py items.csv --column comment --k 5
```

### オプション

| 指定 | 内容 |
|---|---|
| `--column` | CSV の列名または0始まりの列番号(既定:先頭列) |
| `--k` | グループ数。`auto`(既定)は silhouette が最大の k |
| `--k-max` | `auto` で試す k の上限(既定 8) |
| `--model` / `--prefix` | 埋め込みモデルと入力の接頭辞(既定 `cl-nagoya/ruri-v3-310m`。接頭辞は省略するとモデル名から決める) |
| `--seed` | 乱数の種(既定 42)。同じ入力と設定なら同じ結果になる |
| `--device` | 計算デバイス(既定 `auto`)。CUDA, Apple MPS, Intel XPU, DirectML(AMD/Intel/Windows), Huawei NPU, CPU 等を自動で選ぶ |
| `--out` | JSON の保存先。省略すると標準出力に出す |

### 初回と2回目以降

初回は、埋め込みモデル(約1.2GB)とライブラリを取得する。2回目以降はキャッシュを使う。

GPU やアクセラレータ(NVIDIA CUDA, Apple MPS, Intel XPU, DirectML, Huawei NPU 等)があれば自動で使い、無ければ CPU を使う。`--device` で明示的に指定することもできる。

### 実行環境

実行には `uv` と Python 3.12 以上が要る。`install.py` は、`uv` が無ければ入れる。

### 動作を確かめた環境

実モデル(ruri-v3-310m)で、`evals/smoke-items.txt` の 17 件を `--k 3` で分けた結果を、環境ごとに比べた。

| 環境 | デバイス | 結果 |
|---|---|---|
| macOS arm64(Apple Silicon) | cpu | 3 グループに分かれた(v0.4.0 で確認) |
| macOS arm64 | mps(`--device mps`、`auto`) | CPU と、分け方も silhouette(平均 0.0778)も一致した(#26) |
| Linux(GitHub Actions の ubuntu-latest) | cpu | 同じ分け方、同じ silhouette(#25) |
| Windows(GitHub Actions の windows-latest) | cpu | 同じ分け方、同じ silhouette(#25) |
| CUDA・Intel XPU・DirectML・Huawei NPU | — | 未確認(実機が無い)。CUDA が無い環境で `--device cuda` を指定すると、`error: デバイス 'cuda' は利用できません` で止まることだけ確かめた |

Linux と Windows は、`.github/workflows/real-model.yml`(手動で実行する)で確かめた。モデルが約 1.2GB あるので、通常の CI では走らせない。

実機を持っている人は、次で確かめて、結果を [#26](https://github.com/Mr-Kondo/mece-cluster-advisor/issues/26) に書いてほしい。`device` が指定どおりで、silhouette が 0.0778、分け方が `[0, 0, 0, 2, 0, 2, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2]` なら、他の環境と一致している(グループの番号の付け方は、環境によって入れ替わることがある)。

```bash
uv run scripts/mece_cluster.py evals/smoke-items.txt --k 3 --device cuda --out result.json
python3 -c "import json; r = json.load(open('result.json', encoding='utf-8')); print(r['meta']['device'], r['meta']['silhouette_mean'], [i['cluster'] for i in r['items']])"
```

## 結果を読む

出力は JSON である。次の順に読む。

1. `meta.warnings`
2. `meta.k` と `meta.k_selection`
3. `clusters`
4. `boundary_pairs`
5. 必要な分だけ `items`

項目が100件を超えるときは、`items` を全部読まない。

### silhouette の見方

silhouette に合格ラインはない。正解が分かっている3テーマ18件を k=3 で完全に分けても、平均は 0.18 だった。同じデータで k を変えたときの比較に使う。

### 自動で選ぶ k

`--k auto` は、実際の話題の数からずれやすい(ニュース記事の9カテゴリでは小さく、平均約4。短い口語の発話の18分類では、1〜3大きかった)。`meta.warnings` に、そのことが常に出る。目的から k が決まるなら、`--k` で指定して再実行する。評価の詳細は [k-selection.md](k-selection.md) にある。

指標の意味と実例は [references/output-schema.md](../references/output-schema.md) にある。

## 版と実行環境

```bash
python3 scripts/skill_info.py --version                 # 「mece-cluster-advisor 版」の1行
python3 scripts/skill_info.py --model <モデル名>         # 版・OS・アプリ・モデル・日付を JSON で出す
uv run scripts/mece_cluster.py --version                # 同じ1行(依存を解決するため、初回は時間がかかる)
```

`skill_info.py` は標準ライブラリだけで動き、ファイルを書き込まない。保存先 `~/.agents/skill-env/mece-cluster-advisor.json` は標準エラーの `save_to` に出る。保存は実行した側が行う。ユーザー名・ホスト名・パス・メールアドレスは、JSON に出さない。

版は、リポジトリ直下の `VERSION` が持つ。`main` の `VERSION` が変わると、GitHub Actions がタグ `v<版>` と Release(zip・sha256)を作る。ノートは `docs/release-notes/v<版>.md` を使う。

## 確認

モデルを使わない確認:

```bash
uv run scripts/test_mece_cluster.py
python3 scripts/test_skill_info.py
```

`install.py` は GitHub Actions で、Linux(ubuntu-latest)と Windows(windows-latest)の両方で動かして確かめている。確かめている内容は次のとおり。

- `uv run install.py` でインストールできること
- 除外対象(`.claude/` など)が入らないこと
- インストール元と同じ場所からの実行が拒否されること
- アンインストールできること

発動精度の評価は [evals/](../evals/) にある。実行方法と測定結果は [evals/README.md](../evals/README.md) を見る。
