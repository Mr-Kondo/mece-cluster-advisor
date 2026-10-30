"""skill_info.py の確認。標準ライブラリだけで動く。

    python3 scripts/test_skill_info.py
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_info  # noqa: E402

SCRIPT = Path(skill_info.__file__)


def _run(*args: str, home: str | None = None, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", **(extra_env or {})}
    if home:
        env["HOME"] = env["USERPROFILE"] = home
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, encoding="utf-8")


def test_version_file_is_semver_and_matches_output():
    version = (skill_info.SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    out = _run("--version")
    assert out.returncode == 0 and out.stdout.strip() == f"mece-cluster-advisor {version}"


def test_detect_app_prefers_own_marker_over_ai_agent():
    env = {"AI_AGENT": "claude-code_2-1-299_agent", "CODEX_THREAD_ID": "t", "CODEX_VERSION": "0.164.0"}
    assert skill_info.detect_app(env) == {"name": "codex", "version": "0.164.0", "source": "CODEX_THREAD_ID"}


def test_detect_app_reads_ai_agent_and_falls_back():
    assert skill_info.detect_app({"AI_AGENT": "claude-code_2-1-299_agent"}) == {
        "name": "claude-code", "version": "2.1.299", "source": "AI_AGENT"}
    assert skill_info.detect_app({"CLAUDECODE": "1"})["name"] == "claude-code"
    assert skill_info.detect_app({})["name"] == "unknown"


# 実在の名前だと JSON の固定の語と偶然一致しうるので、他と衝突しない目印を使う
SENTINEL = "zz-sentinel-9f3a"
PERSONAL_ENV = {k: f"/home/{SENTINEL}" for k in ("HOME", "USERPROFILE", "USER", "USERNAME", "HOSTNAME", "COMPUTERNAME", "LOGNAME")}


def test_record_has_the_agreed_fields():
    record = skill_info.build_record({"AI_AGENT": "claude-code_2-1-299_agent"}, model="some-model")
    assert record["skill"] == "mece-cluster-advisor" and record["model"] == "some-model"
    assert {"os", "app", "python", "date", "skill_version", "recorded_at"} <= record.keys()
    assert skill_info.build_record({}, model="  ")["model"] == "unknown"


def test_personal_env_values_are_not_echoed():
    env = {**PERSONAL_ENV, "AI_AGENT": "claude-code_2-1-299_agent"}
    assert SENTINEL not in json.dumps(skill_info.build_record(env, model="m"), ensure_ascii=False)
    out = _run("--model", "m", extra_env=PERSONAL_ENV)
    assert out.returncode == 0 and SENTINEL not in out.stdout


def test_untrusted_version_is_not_echoed():
    env = {"CODEX_THREAD_ID": "t", "CODEX_VERSION": f"/Users/{SENTINEL}/x"}
    assert skill_info.detect_app(env)["version"] == "unknown"
    record = skill_info.build_record({}, app="codex", app_version=f"{SENTINEL}@host")
    assert record["app"]["version"] == "unknown" and SENTINEL not in json.dumps(record)
    assert skill_info.safe_version("0.164.0") == "0.164.0" and skill_info.safe_version("1.2.3-beta.1") == "1.2.3-beta.1"


def test_cli_prints_json_and_save_to_and_writes_nothing():
    with tempfile.TemporaryDirectory() as home:
        out = _run("--model", "m", home=home)
        assert out.returncode == 0
        assert json.loads(out.stdout)["model"] == "m"
        assert out.stderr.strip().startswith("save_to:") and "skill-env" in out.stderr
        assert list(Path(home).iterdir()) == [], "スクリプトは何も書き込まない"


def test_main_in_process():
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        assert skill_info.main(["--version"]) == 0
    assert buf.getvalue().startswith("mece-cluster-advisor ")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
