"""モデル/ネットワーク不要の配置・更新・削除の検証。python3 scripts/test_install.py"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "SKILL.md").write_text("new", encoding="utf-8")
        (self.source / "feedback").mkdir()
        (self.source / "feedback" / "private.txt").write_text("private", encoding="utf-8")
        self.target = self.root / "host" / "skills" / installer.SKILL_NAME

    def test_all_targets_update_backup_and_uninstall(self):
        self.assertEqual(set(installer.TARGETS), {"claude", "codex", "gemini"})
        for rel in installer.TARGETS.values():
            target = self.root / rel / installer.SKILL_NAME
            installer.install(self.source, target)
            (target / "local.txt").write_text("keep", encoding="utf-8")
            installer.install(self.source, target)
            self.assertFalse((target / "feedback").exists())
            self.assertFalse((target / "local.txt").exists())
            backups = list((target.parent.parent / ".skill-backups").glob("*/update-*/*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "local.txt").read_text(encoding="utf-8"), "keep")
        with patch.object(Path, "home", return_value=self.root), patch("sys.argv", ["install.py", "--uninstall"]):
            installer.main()
        for rel in installer.TARGETS.values():
            target = self.root / rel / installer.SKILL_NAME
            self.assertFalse(target.exists())
            self.assertTrue((target.parent.parent / ".skill-backups").exists())

    def test_git_failure_does_not_touch_existing_install(self):
        installer.install(self.source, self.target)
        with patch.object(installer, "tracked_files", side_effect=SystemExit("git failed")):
            with self.assertRaises(SystemExit):
                installer.install(self.source, self.target)
        self.assertEqual((self.target / "SKILL.md").read_text(encoding="utf-8"), "new")

    def test_copy_failure_does_not_touch_existing_install(self):
        installer.install(self.source, self.target)
        with patch.object(installer.shutil, "copy2", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                installer.install(self.source, self.target)
        self.assertTrue((self.target / "SKILL.md").is_file())
        self.assertEqual(list(self.target.parent.glob("*-stage-*")), [])

    def test_switch_failure_restores_old_copy(self):
        installer.install(self.source, self.target)
        (self.target / "local.txt").write_text("keep", encoding="utf-8")
        rename = Path.rename

        def fail_stage(path, target):
            if path != self.target and self.target.parent in path.parents and ".skill-backups" not in path.parts:
                raise OSError("switch failed")
            return rename(path, target)

        with patch.object(Path, "rename", fail_stage):
            with self.assertRaises(OSError):
                installer.install(self.source, self.target)
        self.assertTrue((self.target / "local.txt").is_file())
        self.assertEqual(list((self.target.parent.parent / ".skill-backups").glob("*/update-*")), [])

    def test_backup_move_failure_leaves_original_and_no_empty_backup(self):
        installer.install(self.source, self.target)
        with patch.object(Path, "rename", side_effect=PermissionError("file open")):
            with self.assertRaises(PermissionError):
                installer.install(self.source, self.target)
        self.assertTrue((self.target / "SKILL.md").is_file())
        self.assertEqual(list((self.target.parent.parent / ".skill-backups").glob("*/update-*")), [])

    def test_restore_failure_reports_retained_backup(self):
        installer.install(self.source, self.target)
        (self.target / "local.txt").write_text("keep", encoding="utf-8")
        rename = Path.rename

        def fail_new_and_restore(path, target):
            if path != self.target:
                raise PermissionError("file open")
            return rename(path, target)

        with patch.object(Path, "rename", fail_new_and_restore):
            with self.assertRaisesRegex(SystemExit, "旧版は.*保持"):
                installer.install(self.source, self.target)
        backups = list((self.target.parent.parent / ".skill-backups").glob("*/update-*/*"))
        self.assertEqual((backups[0] / "local.txt").read_text(encoding="utf-8"), "keep")

    def test_no_fetch_main_installs_all_without_uv_or_network(self):
        with patch.object(Path, "home", return_value=self.root), \
             patch.object(installer, "ensure_uv", side_effect=AssertionError("uv must not run")), \
             patch.object(installer, "fetch", side_effect=AssertionError("fetch must not run")), \
             patch("sys.argv", ["install.py", "--no-fetch"]):
            installer.main()
        for rel in installer.TARGETS.values():
            target = self.root / rel / installer.SKILL_NAME
            self.assertTrue((target / "references/judgment.md").is_file())
            self.assertFalse((target / "references/update-knowledge.md").exists())
            self.assertFalse((target / "evals").exists())

    def test_main_checks_all_targets_before_updating(self):
        bad = self.root / installer.TARGETS["codex"] / installer.SKILL_NAME
        bad.parent.mkdir(parents=True)
        bad.write_text("not a directory", encoding="utf-8")
        with patch.object(Path, "home", return_value=self.root), \
             patch.object(installer, "install", side_effect=AssertionError("must not update")), \
             patch("sys.argv", ["install.py", "--no-fetch"]):
            with self.assertRaises(SystemExit):
                installer.main()
        self.assertEqual(bad.read_text(encoding="utf-8"), "not a directory")

    def test_tracked_files_only_and_excluded_output(self):
        (self.source / "secret.txt").write_text("private", encoding="utf-8")
        files = [Path("SKILL.md"), Path("feedback/private.txt")]
        with patch.object(installer, "tracked_files", return_value=files):
            installer.install(self.source, self.target)
        self.assertEqual([p.name for p in self.target.iterdir()], ["SKILL.md"])

    def test_only_allowlisted_files_are_shipped(self):
        names = ["SKILL.md", "scripts/mece_cluster.py", "scripts/test_install.py", "references/judgment.md",
                 "references/update-knowledge.md", "docs/k-selection.md", "docs/usage.md", "evals/x.json",
                 "adr/a.md", "knowledge/index.md", "README.md", "install.py", "CLAUDE.local.md",
                 "references/CLAUDE.local.md", "references/__pycache__/x.pyc", "scripts/.env"]
        for n in names:
            f = self.source / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")
        for files in ([Path(n) for n in names], None):  # Git の作業ツリーと、追跡できない場所の両方
            with patch.object(installer, "tracked_files", return_value=files):
                target = self.root / ("t1" if files else "t2") / installer.SKILL_NAME
                installer.install(self.source, target)
            got = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
            self.assertEqual(got, ["SKILL.md", "docs/k-selection.md", "references/judgment.md", "scripts/mece_cluster.py"])

    def test_symlink_is_not_replaced(self):
        real = self.root / "real"
        real.mkdir()
        self.target.parent.mkdir(parents=True)
        try:
            self.target.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(SystemExit):
            installer.install(self.source, self.target)
        self.assertTrue(self.target.is_symlink())


if __name__ == "__main__":
    unittest.main()
