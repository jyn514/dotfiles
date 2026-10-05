#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class GlobLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.repository = self.root / "checkout"
        self.source = self.repository / "config/pi-agent"
        self.source.mkdir(parents=True)
        self.config = self.repository / "install.conf.json"
        self.config.write_text(json.dumps([
            {"defaults": {"link": {"create": True, "relink": True}}},
            {"link": {"$HOME/.pi/agent/": {
                "glob": True,
                "path": "config/pi-agent/**",
            }}},
        ]))
        self.environment = dict(os.environ, HOME=str(self.home))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def install(self) -> subprocess.CompletedProcess[str]:
        backup = subprocess.run(
            ["python3", str(ROOT / "libexec/backup_dotfile_collisions.py"), str(self.config)],
            env=self.environment, cwd=self.root, text=True, capture_output=True,
        )
        if backup.returncode:
            return backup
        return subprocess.run(
            [str(ROOT / "vendor/dotbot/bin/dotbot"), "-d", str(self.repository), "-c", str(self.config)],
            env=self.environment, cwd=self.root, text=True, capture_output=True,
        )

    def test_backs_up_only_matching_files_and_keeps_runtime_state(self) -> None:
        (self.source / "settings.json").write_text('{"theme":"dark"}\n')
        nested = self.source / "templates"
        nested.mkdir()
        (nested / "worker.md").write_text("tracked template\n")
        agent = self.home / ".pi/agent"
        (agent / "sessions").mkdir(parents=True)
        (agent / "sessions/session.jsonl").write_text("session\n")
        (agent / "auth.json").write_text("private credentials\n")
        (agent / "settings.json").write_text("local settings\n")
        (agent / "templates").mkdir()
        (agent / "templates/local.md").write_text("local template\n")

        result = self.install()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(agent.is_symlink())
        self.assertEqual("session\n", (agent / "sessions/session.jsonl").read_text())
        self.assertEqual("private credentials\n", (agent / "auth.json").read_text())
        self.assertEqual("local template\n", (agent / "templates/local.md").read_text())
        self.assertEqual("local settings\n", (self.home / ".local/config/settings.json").read_text())
        self.assertTrue((agent / "settings.json").is_symlink())
        self.assertEqual((self.source / "settings.json").resolve(), (agent / "settings.json").resolve())
        self.assertEqual((nested / "worker.md").resolve(), (agent / "templates/worker.md").resolve())

        # Adding a tracked file needs no corresponding manifest edit.
        (nested / "new-worker.md").write_text("new template\n")
        again = self.install()
        self.assertEqual(0, again.returncode, again.stdout + again.stderr)
        self.assertTrue((agent / "templates/new-worker.md").is_symlink())
        self.assertEqual("local settings\n", (self.home / ".local/config/settings.json").read_text())
        self.assertEqual("session\n", (agent / "sessions/session.jsonl").read_text())

    def test_hidden_file_glob_installs_zsh_config_without_linking_plugins(self) -> None:
        source = self.repository / "config/zsh"
        source.mkdir()
        (source / ".zshrc").write_text("tracked startup\n")
        (source / ".zprofile").write_text("tracked login\n")
        (source / "not-a-dotfile").write_text("not installed\n")
        self.config.write_text(json.dumps([
            {"defaults": {"link": {"create": True, "relink": True}}},
            {"link": {"$HOME/.config/zsh/": {"glob": True, "path": "config/zsh/.*"}}},
        ]))
        destination = self.home / ".config/zsh"
        (destination / "antidote").mkdir(parents=True)
        (destination / "antidote/antidote.zsh").write_text("installed plugin\n")
        (destination / ".zshrc").write_text("local startup\n")
        (destination / ".zsh_plugins.zsh").write_text("generated plugin loader\n")

        result = self.install()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for name in (".zshrc", ".zprofile"):
            with self.subTest(name=name):
                self.assertTrue((destination / name).is_symlink())
                self.assertEqual((source / name).resolve(), (destination / name).resolve())
        self.assertEqual("local startup\n", (self.home / ".local/config/.zshrc").read_text())
        self.assertEqual("installed plugin\n", (destination / "antidote/antidote.zsh").read_text())
        self.assertEqual("generated plugin loader\n", (destination / ".zsh_plugins.zsh").read_text())
        self.assertFalse((destination / "not-a-dotfile").exists())
        self.assertFalse(destination.is_symlink())

    def test_backup_failure_leaves_configuration_and_state_untouched(self) -> None:
        (self.source / "settings.json").write_text("tracked settings\n")
        agent = self.home / ".pi/agent"
        agent.mkdir(parents=True)
        (agent / "settings.json").write_text("local settings\n")
        (agent / "auth.json").write_text("private credentials\n")
        (self.home / ".local").write_text("blocks backup directory creation\n")

        result = self.install()

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("local settings\n", (agent / "settings.json").read_text())
        self.assertFalse((agent / "settings.json").is_symlink())
        self.assertEqual("private credentials\n", (agent / "auth.json").read_text())

    def test_installs_shared_source_symlinks_and_preserves_excluded_files(self) -> None:
        shared = self.repository / "config/agents"
        shared.mkdir()
        (shared / "breq.md").write_text("shared instructions\n")
        (self.source / "breq.md").symlink_to("../agents/breq.md")
        (self.source / "local.json").write_text("not installed\n")
        configuration = json.loads(self.config.read_text())
        configuration[1]["link"]["$HOME/.pi/agent/"]["exclude"] = ["config/pi-agent/local.json"]
        self.config.write_text(json.dumps(configuration))
        agent = self.home / ".pi/agent"
        agent.mkdir(parents=True)
        (agent / "local.json").write_text("local state\n")

        result = self.install()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("shared instructions\n", (agent / "breq.md").read_text())
        self.assertEqual((shared / "breq.md").resolve(), (agent / "breq.md").resolve())
        self.assertEqual("local state\n", (agent / "local.json").read_text())
        self.assertFalse((self.home / ".local/config/local.json").exists())


if __name__ == "__main__":
    unittest.main()
