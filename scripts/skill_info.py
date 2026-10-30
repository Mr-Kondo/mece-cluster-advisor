#!/usr/bin/env python3
"""スキルの版と、実行環境(OS・アプリ・モデル・日付)を JSON で標準出力に出す。読み取り専用。

    skill_info.py --model NAME   # 版と環境を JSON で出す。標準エラーに、保存先の目安(save_to)も出す
    skill_info.py --version      # 「スキル名 版」の1行だけ

このスクリプトは、ファイルを書き込まない。共有のエージェントフォルダ(~/.agents/skill-env/<スキル名>.json)へ
保存するのは、実行した側(エージェント)で、標準エラーの save_to の場所へ、標準出力の JSON をそのまま書く。
モデル名は環境から分からないので、実行する側が --model で渡す。渡さなければ unknown。
アプリは、環境変数から推定する。違えば --app で指定する。
ユーザー名・ホスト名・パス・メールアドレスは、JSON に出さない。標準ライブラリだけで動く(uv も要らない)。

終了コード: 0=出した。
"""

import argparse
import json
import os
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

NAME = "mece-cluster-advisor"  # インストール先のフォルダ名に依らず、スキル名で記録する
SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
SAVE_TO = Path.home() / ".agents" / "skill-env" / f"{NAME}.json"
# アプリ自身が設定する目印(環境変数, アプリ名, 版を持つ環境変数)。子プロセスは親の AI_AGENT を引き継ぐので、これを先に調べる。
# 入れ子の起動(例: Claude Code から Codex を呼ぶ)では、子のアプリになる。
APP_MARKERS = (("CODEX_THREAD_ID", "codex", "CODEX_VERSION"), ("OPENCODE", "opencode", None), ("HERMES_AGENT", "hermes", None))
FALLBACK_MARKERS = (("CLAUDECODE", "claude-code"), ("GEMINI_CLI", "gemini-cli"))  # AI_AGENT が無い環境の目安


VERSION_RE = re.compile(r"^\d+(?:\.\d+){0,3}(?:[-+][0-9A-Za-z.]+)?$")


def safe_version(value: str) -> str:
    """版として読める形だけを通す。環境変数に紛れたパスやユーザー名を、JSON に出さない。"""
    value = (value or "").strip()
    return value if VERSION_RE.fullmatch(value) else "unknown"


def read_version() -> str:
    try:
        return (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def detect_app(env) -> dict:
    """アプリ自身の目印、AI_AGENT(例: claude-code_2-1-299_agent)、目安の順に調べる。"""
    for variable, name, version_variable in APP_MARKERS:
        if env.get(variable):
            return {"name": name, "version": safe_version(env.get(version_variable or "", "")), "source": variable}
    match = re.match(r"^([a-z][a-z-]*)_(\d+(?:-\d+)*)(?:_|$)", env.get("AI_AGENT", ""))
    if match:
        return {"name": match.group(1), "version": match.group(2).replace("-", "."), "source": "AI_AGENT"}
    for variable, name in FALLBACK_MARKERS:
        if env.get(variable):
            return {"name": name, "version": "unknown", "source": variable}
    return {"name": "unknown", "version": "unknown", "source": "none"}


def build_record(env, model: str = "", app: str = "", app_version: str = "") -> dict:
    detected = detect_app(env)
    if app:
        detected = {"name": app, "version": safe_version(app_version), "source": "argument"}
    elif app_version:
        detected["version"] = safe_version(app_version)
    now = datetime.now().astimezone()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "skill-env",
        "skill": NAME,
        "skill_version": read_version(),
        "os": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "app": detected,
        "model": model.strip() or "unknown",
        "python": platform.python_version(),
        "date": now.date().isoformat(),
        "recorded_at": now.isoformat(timespec="seconds"),
    }


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="スキルの版と実行環境を JSON で出す。")
    parser.add_argument("--version", action="store_true", help="「スキル名 版」の1行だけを出す")
    parser.add_argument("--model", default="", help="実行しているモデル名(環境から分からないので、実行する側が渡す)")
    parser.add_argument("--app", default="", help="アプリ名。環境からの推定が違うときだけ")
    parser.add_argument("--app-version", default="", help="アプリの版。分かるときだけ")
    args = parser.parse_args(argv)
    if args.version:
        print(f"{NAME} {read_version()}")
        return 0
    record = build_record(os.environ, args.model, args.app, args.app_version)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"save_to: {SAVE_TO}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
