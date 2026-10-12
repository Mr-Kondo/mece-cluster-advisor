#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""スキルを Claude Code / Codex へインストール(更新)・アンインストールする。

    uv run install.py                   # 両方へインストール。再実行すると更新になる
    uv run install.py --target claude   # Claude Code のみ
    uv run install.py --uninstall       # 両方から削除

uv がなくても python3 install.py(Windows は python install.py)で動く。Mac と Windows で同じコマンドである。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SKILL_NAME = "mece-cluster-advisor"
TARGETS = {"claude": ".claude/skills", "codex": ".agents/skills"}  # ホームからの相対
# 実行環境の設定(トークンを含む)、キャッシュ、リポジトリの管理ファイルはコピーしない
EXCLUDE = (".git", ".gitignore", ".claude", ".DS_Store", "__pycache__")


def install(source: Path, target: Path) -> None:
    """source の中身を target へ写す。既にあれば消して作り直す(更新)。"""
    if source == target.resolve():
        raise SystemExit(f"error: インストール元と先が同じ({target})。リポジトリの install.py を実行する。")
    if not (source / "SKILL.md").is_file():
        raise SystemExit(f"error: {source} に SKILL.md がない。リポジトリの直下で実行する。")
    if target.is_dir():
        shutil.rmtree(target)  # 更新で消えたファイルを残さない
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*EXCLUDE))
    print(f"installed: {target}")


def main() -> None:
    p = argparse.ArgumentParser(description="スキルを Claude Code / Codex へインストール・アンインストールする")
    p.add_argument("--target", choices=[*TARGETS, "all"], default="all", help="対象(既定 all)")
    p.add_argument("--uninstall", action="store_true", help="削除する")
    args = p.parse_args()

    source = Path(__file__).resolve().parent
    for name in TARGETS if args.target == "all" else [args.target]:
        target = Path.home() / TARGETS[name] / SKILL_NAME
        if not args.uninstall:
            install(source, target)
        elif target.is_dir():
            shutil.rmtree(target)
            print(f"removed: {target}")
        else:
            print(f"not installed: {target}")


if __name__ == "__main__":
    main()
