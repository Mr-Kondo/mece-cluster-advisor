# 操作方法

このファイルは、[README.md](../README.md) の概要を、実際の操作手順にしたものである。コマンドはすべてリポジトリ直下で実行する。

## 目次

- [必要な環境](#必要な環境)
- [インストール](#インストール)
- [スキルとして使う](#スキルとして使う)
- [スクリプトを直接使う](#スクリプトを直接使う)
- [結果を読む](#結果を読む)
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

- `.claude/`:実行環境の設定を含み、トークンも入るため、コピーしない。
- `__pycache__/`:キャッシュのため、コピーしない。

### `--purge` が消すもの

- モデルのキャッシュ:`~/.cache/huggingface/hub/`。`HF_HOME` か `HF_HUB_CACHE` を設定していれば、そこ。
- このスキルのスクリプト用に uv が作った実行環境のキャッシュ:`uv cache dir` の下。実測で約1.5GB。

次は消えない。

- 展開済みのパッケージ:他のプロジェクトと共有しているため。

これも消したいときは、次を使い分ける。

- `uv cache clean`:キャッシュを全消しする。
- `uv cache prune`:未使用の分だけ消す。

### Codex の注意

Codex はスキル一覧で description を短く切るため、発動が弱くなる(未検証)。

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

指標の意味と実例は [references/output-schema.md](../references/output-schema.md) にある。

## 確認

モデルを使わない確認:

```bash
uv run scripts/test_mece_cluster.py
```

`install.py` は GitHub Actions で、Linux(ubuntu-latest)と Windows(windows-latest)の両方で動かして確かめている。確かめている内容は次のとおり。

- `uv run install.py` でインストールできること
- 除外対象(`.claude/` など)が入らないこと
- インストール元と同じ場所からの実行が拒否されること
- アンインストールできること

発動精度の評価は [evals/](../evals/) にある。実行方法と測定結果は [evals/README.md](../evals/README.md) を見る。
