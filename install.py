#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""スキルを Claude Code / Codex へインストール(更新)・アンインストールする。

    uv run install.py                  # インストール(更新)と、依存とモデルの取得
    uv run install.py --target claude  # Claude Code のみ
    uv run install.py --no-fetch       # 依存とモデルの取得をしない
    uv run install.py --uninstall      # スキルを削除
    uv run install.py --purge          # スキルと、取得したモデルと依存のキャッシュを削除

uv がなければ、公式のインストーラで入れてから続ける。Mac と Windows で同じコマンドである。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_NAME = "mece-cluster-advisor"
TARGETS = {"claude": ".claude/skills", "codex": ".agents/skills"}  # ホームからの相対
# 実行環境の設定(トークンを含む)、仮想環境、検証用の出力、キャッシュ、リポジトリの管理ファイル、
# 手元の私的な指示ファイル(CLAUDE.local.md など)はコピーしない
EXCLUDE = (".git", ".gitignore", ".claude", ".codex", ".serena", ".venv", "feedback", ".DS_Store", "__pycache__", "*.local.md")
MODEL = "cl-nagoya/ruri-v3-310m"  # scripts/mece_cluster.py の既定と同じ
UV_URL = "https://docs.astral.sh/uv/"

# 日本語を出せないコードページ(Windows の cp1252 など)でも、落ちずに ? で出す
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


# ---------------------------------------------------------------- インストール
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


# ---------------------------------------------------------------- 実行時の前提
def ensure_uv() -> str:
    """uv の実行ファイルを返す。無ければ公式インストーラで入れる(実行時の前提)。"""
    found = shutil.which("uv")
    if found:
        return found
    print("uv が無いので公式インストーラで入れる", file=sys.stderr)
    if os.name == "nt":
        cmd = ["powershell", "-ExecutionPolicy", "ByPass", "-c", "irm https://astral.sh/uv/install.ps1 | iex"]
    else:
        cmd = ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
    subprocess.run(cmd, check=False)
    # インストーラは ~/.local/bin に入れる。このプロセスの PATH には反映されないので、直接探す
    exe = Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    if exe.is_file():
        return str(exe)
    raise SystemExit(f"error: uv を入れられなかった。手動で入れる: {UV_URL}")


def fetch(uv: str, script: Path) -> None:
    """依存と埋め込みモデルを先に取得する。仮の4件を実際に流して、動くことまで確かめる。"""
    print("依存とモデルを取得する(モデルだけで約1.2GB)。初回だけ時間がかかる", file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        items = Path(tmp) / "items.txt"
        items.write_text("テスト\n例\n見本\nサンプル\n", encoding="utf-8")
        env = {**os.environ, "PYTHONUTF8": "1"}  # 子プロセスの日本語と進捗バーで落ちないように
        code = subprocess.run([uv, "run", str(script), str(items), "--out", str(Path(tmp) / "result.json")], env=env).returncode
    if code != 0:
        raise SystemExit("error: 取得に失敗した。ネットワークを確かめるか、--no-fetch で後回しにする。")


# ---------------------------------------------------------------- 削除
def model_cache_dir() -> Path:
    """埋め込みモデルのキャッシュ。huggingface_hub と同じ場所を選ぶ。"""
    name = f"models--{MODEL.replace('/', '--')}"
    if hub := os.environ.get("HF_HUB_CACHE"):
        return Path(hub) / name
    return Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub" / name


def dir_size(path: Path) -> float:
    """ディレクトリの中身の合計(GB)。"""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e9


def purge_model() -> None:
    cache = model_cache_dir()
    if not cache.is_dir():
        print(f"not found: {cache}")
        return
    size = dir_size(cache)
    shutil.rmtree(cache)
    print(f"removed: {cache} ({size:.1f}GB)")


def purge_uv_envs(source: Path) -> None:
    """uv がこのスキルのスクリプト用に作ったキャッシュ環境を消す。依存の実体はここにある。"""
    uv = shutil.which("uv")
    if not uv:
        print("uv が無いので、依存のキャッシュは消していない(手動: uv cache clean)", file=sys.stderr)
        return
    out = subprocess.run([uv, "cache", "dir"], capture_output=True, text=True).stdout.strip()
    if not out:
        print("uv cache dir が分からず、依存のキャッシュは消していない", file=sys.stderr)
        return
    cache = Path(out)
    # shortcut: uv の内部レイアウト(environments-v2/<スクリプト名>-<ハッシュ>)。変われば見つからないだけ
    removed = 0
    freed = 0.0
    for script in sorted((source / "scripts").glob("*.py")):
        for env in cache.glob(f"environments-v2/{script.stem.replace('_', '-')}-*"):
            freed += dir_size(env)
            shutil.rmtree(env)
            removed += 1
    if removed:
        print(f"removed: uv のキャッシュ環境 {removed}個 ({freed:.1f}GB)")
    else:
        print(f"not found: {cache}/environments-v2")
    print("展開済みのパッケージは他のプロジェクトと共有なので残る。全部消すなら uv cache clean", file=sys.stderr)


# ---------------------------------------------------------------- CLI
def main() -> None:
    p = argparse.ArgumentParser(description="スキルを Claude Code / Codex へインストール・アンインストールする")
    p.add_argument("--target", choices=[*TARGETS, "all"], default="all", help="対象(既定 all)")
    p.add_argument("--uninstall", action="store_true", help="スキルを削除する")
    p.add_argument("--purge", action="store_true", help="スキルと、取得したモデルと依存のキャッシュを削除する")
    p.add_argument("--no-fetch", action="store_true", help="依存とモデルの取得をしない")
    args = p.parse_args()

    source = Path(__file__).resolve().parent
    names = list(TARGETS) if args.target == "all" else [args.target]

    if args.uninstall or args.purge:
        for name in names:
            target = Path.home() / TARGETS[name] / SKILL_NAME
            if target.is_dir():
                shutil.rmtree(target)
                print(f"removed: {target}")
            else:
                print(f"not installed: {target}")
        if args.purge:
            purge_model()
            purge_uv_envs(source)
        return

    uv = ensure_uv()
    first = None
    for name in names:
        target = Path.home() / TARGETS[name] / SKILL_NAME
        install(source, target)
        first = first or target
    if not args.no_fetch:
        fetch(uv, first / "scripts" / "mece_cluster.py")
    print("消すときは --uninstall、取得したモデルも消すなら --purge")


if __name__ == "__main__":
    main()
