---
status: accepted
date: 2026-11-11
supersedes: 2026-11-02-wikiskill-update-knowledge.md のインストーラー部分
---

# install.py を廃止し、配置と更新を skills CLI に一本化する

## 文脈

`npx skills add` / `update` / `remove` で3環境へ配置できることを v0.4.13 で確認した。`install.py` と併存すると、配置先の所有者(CLIか手動コピーか)が混ざり、手順と保守が二重になる。利用者から廃止の指示があった。

## 決定

`install.py` と `scripts/test_install.py`、それに結びついたCI・Release検証・文書を削除する。配置・更新・削除は `npx skills` に任せる。

## 失うもの

- 許可リストによる配置の絞り込み(CLIはリポジトリの補助文書・評価用ファイルも配置する)。
- uv の自動導入、初回のモデル先取得、`--purge`。初回のスクリプト実行時の取得と了承(SKILL.md 手順3)に一本化し、削除は手動手順を docs/usage.md に書く。
- 更新時の旧版バックアップ。
- `npx skills update` は、ref 未指定で登録すると既定ブランチを追跡し、Releaseのタグを選ばない。

## 撤退条件

CLIが特定のホストへ配置できない、または補助文書の混入が実害を出す場合は、配置用スクリプトを再検討する。
