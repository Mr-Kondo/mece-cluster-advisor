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
| `uv` | [公式の手順](https://docs.astral.sh/uv/)で入れる |
| Python | 3.12 以上(スクリプトを実行するとき) |
| ディスク | 初回の取得で、埋め込みモデルと依存をダウンロードする |
| 通信 | 初回の取得と更新確認に必要。以降はオフラインでも動く |

## インストール

<a id="skills-cli"></a>

### skills CLIでの登録・更新・削除

[`skills` CLI](https://github.com/vercel-labs/skills)で取得元を登録すると、`npx skills update` の対象になる。手動でコピーしただけのスキルは自動では登録されない。Node.jsの要件はCLIの公式案内を確認する。

```bash
# 初回登録。表示される配置先と上書き対象を確認する
npx skills add Mr-Kondo/mece-cluster-advisor -g --skill mece-cluster-advisor -a claude-code codex antigravity
# このスキルだけを更新
npx skills update mece-cluster-advisor -g
# CLI管理の配置を削除
npx skills remove mece-cluster-advisor -g -y
```

登録後は `npx skills update` だけでも更新できるが、他の登録済みスキルも更新対象になる。プロジェクト内で実行するときは、対話でグローバルを選ぶか `-g` を付ける。ref を指定せずに登録した場合、CLIの更新は既定ブランチを追跡し、最新Releaseのタグを選ぶものではない。

既存の配置から移行するときは、ホストを閉じ、上書きされるスキルフォルダを `skills/` の外へ退避してから登録する。このMacで確認したCLI 1.7.6は `~/.agents/skills/mece-cluster-advisor/` を実体とする共有配置で、Claude Codeは `~/.claude/skills/` からリンクされ、CodexとAntigravityは共有配置を使う。CLIの版により配置先が異なるため、登録時の表示を確認する。更新後は共有配置の `VERSION` で版を確認できる。旧インストーラ(v0.4.13まで)のAntigravity向け配置先は `~/.gemini/config/skills/` である。旧配置を使う環境では、その旧フォルダも退避し、同名のシンボリックリンクを共有配置へ向ける。この追加リンクはCLI管理外なので、削除時は別途取り除く。

CLIはリポジトリの補助文書・評価用ファイルも配置する。uv・Python依存・モデルの取得は行わない。必要な取得は初回のスクリプト実行時に行う(`SKILL.md` の手順3)。

### 取得したモデルと依存を消す

スキルを削除しても、初回の実行で取得したものは残る。不要なら手動で消す。

- モデルのキャッシュ:`~/.cache/huggingface/hub/models--cl-nagoya--ruri-v3-310m`。`HF_HOME` か `HF_HUB_CACHE` を設定していれば、その下。
- uv の実行環境と展開済みパッケージ:`uv cache clean` で全消しする(他のプロジェクトの分も消える)。未使用の分だけなら `uv cache prune`。

### Codex の注意

Codex は、スキル一覧の description を、スキルの数に応じて切る。スキルが多い環境では、前方の十数文字しか残らない。この Mac(Codex 0.164.0、スキル 200 件超)では、このスキルは `項目の集合(アイデア、要件、` までしか見えなかった。

`evals/trigger-eval.json` の 24 件を `codex exec` で流した結果は、肯定 12 件のうち 10 件で発動し、否定 12 件では発動しなかった。外れたのは、「MECE」と書かれていない依頼(問い合わせ件名の分類の切り口の提案、タイトル案のグルーピング)だった。名前と依頼文の語に頼って発動しているので、スキルが多い環境では、依頼に「MECE」「分類」などを入れると確実になる。

description の前方を「MECE分類・グルーピング・…」に書き換える案も試したが、採用しなかった。発動は肯定 8/12 と 7/12(2 回)で、現状の 10/12 より下がった。否定 12 件は 0 件のままだった([#36](https://github.com/Mr-Kondo/mece-cluster-advisor/issues/36))。切られた後の見え方は変わったが、発動の手がかりになったのは、前方の語ではなかった。

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
| `--device` | 計算デバイス(既定 `auto`)。下の「計算デバイス」を見る |
| `--out` | JSON の保存先。省略すると標準出力に出す |

### 初回と2回目以降

初回は、埋め込みモデル(約1.2GB)とライブラリを取得する。2回目以降はキャッシュを使う。

### 計算デバイス

`--device auto`(既定)は、次の順に使えるものを選び、どれも無ければ CPU を使う。

CUDA、Apple MPS、Intel XPU、DirectML(Windows の AMD・Intel。`torch-directml` が要る)、Huawei NPU、Intel HPU、`torch.accelerator` が返すデバイス

- `auto` で選んだデバイスで、モデルの読み込みか埋め込みが失敗したら、警告を出して CPU でやり直す。`OSError`(モデルの取得の失敗など)は、やり直さずに止める。
- `auto` が、最初から CPU を選んだときは、注意を出すことがある。`nvidia-smi` か `rocm-smi` があれば、「GPU 対応の torch を入れる」と案内する。どちらも無く、Windows なら、DirectML を案内する。上の失敗から CPU に戻ったときは、この注意は出ない。
- `--device cuda` のように明示して、そのデバイスの種類が使えないときは、`error: デバイス 'cuda' は利用できません` で止まる。`--device auto` か `cpu` を指定する。使える種類でも、存在しない番号を指定したときなどは、別のエラーで止まる。どちらも CPU には戻さない。

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

実機を持っている人は、次で確かめて、結果を [#26](https://github.com/Mr-Kondo/mece-cluster-advisor/issues/26) に書いてほしい。他の環境と一致している条件は、次の2つである。グループの番号の付け方は、環境によって入れ替わることがある。

- `device` が指定どおりである。
- silhouette が 0.0778 で、分け方が `[0, 0, 0, 2, 0, 2, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2]` である。

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

単体テストは GitHub Actions で、Linux(ubuntu-latest)と Windows(windows-latest)の両方で動かして確かめている。

発動精度の評価は [evals/](../evals/) にある。実行方法と測定結果は [evals/README.md](../evals/README.md) を見る。
