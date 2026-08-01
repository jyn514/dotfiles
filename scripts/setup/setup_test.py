#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DotfileSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        # codex.rules is deliberately hard-linked, so keep the fake home on the
        # repository filesystem.
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
        command = env.get("DOTFILES_SETUP_COMMAND", "./setup.sh dotfiles")
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
        for line in (ROOT / "install/config.txt").read_text().splitlines():
            name, destination = line.split("=", 1)
            destinations[name] = destination
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
            destination = self.destination_for(source)
            self.assertTrue(destination.exists(), destination)
            if source.name == "codex.rules":
                self.assertFalse(destination.is_symlink())
                self.assertTrue(os.path.samefile(source, destination))
            else:
                self.assertTrue(destination.is_symlink(), destination)
                self.assertEqual(source.resolve(), destination.resolve())

    def test_installs_every_config_entry_in_an_empty_home(self) -> None:
        result = self.run_setup()

        self.assertEqual(0, result.returncode, result.stderr)
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


if __name__ == "__main__":
    unittest.main()
