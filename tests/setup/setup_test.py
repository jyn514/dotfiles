#!/usr/bin/env python3

import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DotfileSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=ROOT)
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
    def config_destinations() -> dict[str, str]:
        destinations: dict[str, str] = {}
        config = json.loads((ROOT / "install.conf.json").read_text())
        links = next(directive["link"] for directive in config if "link" in directive)
        for destination, specification in links.items():
            source = specification if isinstance(specification, str) else specification["path"]
            if destination.startswith("$HOME/"):
                destinations[Path(source).name] = destination.removeprefix("$HOME/")
        return destinations

    def destination_for(self, source: Path) -> Path:
        if source.name == "jj.toml":
            return self.home / ".config/jj/custom.toml"
        if source.name.startswith("git"):
            return self.home / ".config/git" / source.name.removeprefix("git")
        relative = self.config_destinations().get(source.name, f".{source.name}")
        return self.home / relative

    def assert_all_dotfiles_installed(self) -> None:
        for source in (ROOT / "config").iterdir():
            # Supporting assets can live below config/ without being Dotbot links.
            if not source.is_file():
                continue
            destination = self.destination_for(source)
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
