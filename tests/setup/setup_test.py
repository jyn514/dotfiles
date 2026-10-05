#!/usr/bin/env python3

import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "libexec"))
from dotfile_links import configured_links


class DotfileSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name) / "home"
        self.home.mkdir()
        self.bin = Path(self.tempdir.name) / "bin"
        self.bin.mkdir()
        jj = self.bin / "jj"
        jj.write_text(
            "#!/bin/sh\n"
            'if [ "$1 $2 $3" = "config path --user" ]; then\n'
            '  printf "%s\\n" "$HOME/.config/jj/custom.toml"\n'
            "fi\n"
        )
        jj.chmod(0o755)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_setup(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:{env['PATH']}",
        )
        command = f"{env.get('SETUP_COMMAND_PREFIX') or './setup'} dotfiles"
        return subprocess.run(
            ["sh", "-c", command],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def configured_links() -> list[tuple[str, Path]]:
        return list(configured_links(ROOT / "install.conf.json").items())

    def destinations_for(self, source: Path) -> list[Path]:
        destinations = []
        for destination, configured_source in self.configured_links():
            if configured_source != source:
                continue
            if destination.startswith("$HOME/"):
                destinations.append(self.home / destination.removeprefix("$HOME/"))
            elif destination == "$JJ_CONFIG_PATH":
                destinations.append(self.home / ".config/jj/custom.toml")
        if destinations:
            return destinations
        if source.name.startswith("git"):
            return [self.home / ".config/git" / source.name.removeprefix("git")]
        return [self.home / f".{source.name}"]

    def assert_all_dotfiles_installed(self) -> None:
        sources = {
            source
            for _, source in self.configured_links()
            if source.is_file() and source.is_relative_to(ROOT / "config")
        }
        for source in sorted(sources):
            for destination in self.destinations_for(source):
                self.assertTrue(destination.exists(), destination)
                self.assertTrue(destination.is_symlink(), destination)
                self.assertEqual(source.resolve(), destination.resolve())

    def test_installs_every_config_entry_in_an_empty_home(self) -> None:
        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("Creating symlink", result.stdout)
        self.assertNotIn("Creating hardlink", result.stdout)
        self.assert_all_dotfiles_installed()
        self.assertTrue((self.home / ".config/git/credentials").is_file())
        self.assertTrue((self.home / ".local/state/zsh").is_dir())

    def test_pi_glob_installs_resources_without_moving_sessions_or_credentials(self) -> None:
        agent = self.home / ".pi/agent"
        (agent / "sessions").mkdir(parents=True)
        (agent / "sessions/existing.jsonl").write_text("session\n")
        (agent / "auth.json").write_text("credentials\n")
        (agent / "settings.json").write_text("local Pi settings\n")
        # Previous setup linked the entire template directory, not its files.
        templates = agent / "pi-codex-subagents/agents"
        templates.parent.mkdir()
        templates.symlink_to(ROOT / "config/agents/pi/pi-codex-subagents/agents", target_is_directory=True)

        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("session\n", (agent / "sessions/existing.jsonl").read_text())
        self.assertEqual("credentials\n", (agent / "auth.json").read_text())
        self.assertEqual("local Pi settings\n", (self.home / ".local/config/settings.json").read_text())
        self.assertFalse(agent.is_symlink())
        self.assertTrue(templates.is_symlink())
        self.assertEqual((ROOT / "config/pi-agent/pi-codex-subagents/agents").resolve(), templates.resolve())
        for name in ("settings.json", "AGENTS.md", "breq.md", "mcp.json", "keybindings.json",
                     "pi-codex-subagents/config.json", "pi-extensions/index.ts", "pi-extensions/compaction.md"):
            with self.subTest(name=name):
                self.assertTrue((agent / name).is_symlink())
                self.assertEqual((ROOT / "config/pi-agent" / name).resolve(), (agent / name).resolve())

    def test_grouped_configs_migrate_old_links_without_moving_local_resources(self) -> None:
        installed = {
            "Library/LaunchAgents/com.jyn.agent-room.plist": "config/LaunchAgents/com.jyn.agent-room.plist",
            ".config/nvim/init.lua": "config/nvim/init.lua",
            ".config/nvim/after/queries/markdown/textobjects.scm": "config/nvim/after/queries/markdown/textobjects.scm",
            ".config/tmux/tmux.conf": "config/tmux/tmux.conf",
            ".config/tmux/attach-session.sh": "libexec/tmux/attach-session.sh",
            ".config/tmux/dragon.sh": "libexec/tmux/dragon.sh",
            ".config/tmux/renumber-sessions.sh": "libexec/tmux/renumber-tmux-sessions.sh",
            ".config/tmux/set-env.sh": "libexec/tmux/set-tmux-env.sh",
            ".config/tmux/picker-action": "bin/picker-action",
            ".config/zsh/.zprofile": "config/zsh/.zprofile",
            ".config/zsh/.zsh_plugins.txt": "config/zsh/.zsh_plugins.txt",
            ".config/zsh/.zshrc": "config/zsh/.zshrc",
            ".config/kitty/kitty.conf": "config/kitty/kitty.conf",
            ".config/kitty/campbell.conf": "config/kitty/campbell.conf",
            ".local/share/applications/Helix.desktop": "config/applications/Helix.desktop",
            ".local/share/applications/fx-usercreated-1.desktop": "config/applications/fx-usercreated-1.desktop",
            ".local/share/applications/nvim.desktop": "config/applications/nvim.desktop",
            ".local/share/applications/spotify-qt.desktop": "config/applications/spotify-qt.desktop",
        }
        old_links = {
            ".config/nvim/init.lua": "config/nvim.lua",
            ".config/tmux/tmux.conf": "config/tmux.conf",
            ".config/zsh/.zprofile": "config/zprofile",
            ".config/kitty/campbell.conf": "config/kitty-campbell.conf",
            ".local/share/applications/fx-usercreated-1.desktop": "config/fx.desktop",
        }
        for name, old_source in old_links.items():
            destination = self.home / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(ROOT / old_source)
        local_resources = (
            "Library/LaunchAgents/local.plist",
            ".config/nvim/local/plugin.lua",
            ".config/tmux/plugins/tpm/tpm",
            ".config/zsh/antidote/antidote.zsh",
            ".config/zsh/.zsh_plugins.zsh",
            ".config/kitty/kitty_search/search.py",
            ".local/share/applications/nvim-generated.desktop",
        )
        for name in local_resources:
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("local resource\n")
        collision = self.home / ".config/kitty/kitty.conf"
        collision.write_text("local Kitty settings\n")

        first = self.run_setup()
        second = self.run_setup()

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("local Kitty settings\n", (self.home / ".local/config/kitty.conf").read_text())
        for name, source in installed.items():
            with self.subTest(installed=name):
                destination = self.home / name
                self.assertTrue(destination.is_symlink())
                self.assertEqual((ROOT / source).resolve(), destination.resolve())
        for name in local_resources:
            with self.subTest(preserved=name):
                self.assertEqual("local resource\n", (self.home / name).read_text())
                self.assertFalse((self.home / name).is_symlink())

    def test_backs_up_existing_file_and_replaces_stale_symlink(self) -> None:
        zshrc = self.home / ".config/zsh/.zshrc"
        zshrc.parent.mkdir(parents=True)
        zshrc.write_text("local customization\n")
        inputrc = self.home / ".config/readline/inputrc"
        inputrc.parent.mkdir(parents=True)
        inputrc.symlink_to(self.home / "missing")

        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "local customization\n",
            (self.home / ".local/config/.zshrc").read_text(),
        )
        self.assert_all_dotfiles_installed()

    def test_second_run_is_idempotent(self) -> None:
        first = self.run_setup()
        second = self.run_setup()

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assert_all_dotfiles_installed()

    def test_collision_is_backed_up_before_target_is_linked(self) -> None:
        destination = self.home / ".config/readline/inputrc"
        destination.parent.mkdir(parents=True)
        destination.write_text("machine-local inputrc\n")

        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        backup = self.home / ".local/config/inputrc"
        self.assertEqual("machine-local inputrc\n", backup.read_text())
        self.assertTrue(destination.is_symlink())
        self.assertEqual((ROOT / "config/inputrc").resolve(), destination.resolve())

    def test_collision_replaces_an_existing_backup_with_the_same_name(self) -> None:
        destination = self.home / ".config/readline/inputrc"
        destination.parent.mkdir(parents=True)
        destination.write_text("current machine customization\n")
        backup = self.home / ".local/config/inputrc"
        backup.parent.mkdir(parents=True)
        backup.write_text("older machine customization\n")

        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("current machine customization\n", backup.read_text())
        self.assertTrue(destination.is_symlink())
        self.assertEqual((ROOT / "config/inputrc").resolve(), destination.resolve())

    def test_jj_uses_reported_user_config_path_and_backs_up_collision(self) -> None:
        destination = self.home / ".config/jj/custom.toml"
        destination.parent.mkdir(parents=True)
        destination.write_text("user = 'local'\n")

        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "user = 'local'\n",
            (self.home / ".local/config/custom.toml").read_text(),
        )
        self.assertTrue(destination.is_symlink())
        self.assertEqual((ROOT / "config/jj.toml").resolve(), destination.resolve())
        self.assertFalse((self.home / ".jj.toml").exists())

    def test_jj_falls_back_to_default_user_config_path(self) -> None:
        jj = self.bin / "jj"
        jj.write_text("#!/bin/sh\nexit 1\n")
        jj.chmod(0o755)
        destination = self.home / ".config/jj/config.toml"

        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(destination.is_symlink())
        self.assertEqual((ROOT / "config/jj.toml").resolve(), destination.resolve())
        self.assertFalse((self.home / ".jj.toml").exists())


if __name__ == "__main__":
    unittest.main()
