"""Exercise local package setup with no preinstalled Neovim plugins."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class NeovimSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nvim setup ")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.home = self.directory / "home"
        (self.home / ".config/fish").mkdir(parents=True)
        (self.home / ".config/fish/fish_plugins").touch()
        (self.home / ".config/zsh/antidote").mkdir(parents=True)
        self.checkout = self.directory / "checkout"
        self.checkout.mkdir()
        (self.checkout / "lib").symlink_to(ROOT / "lib", target_is_directory=True)
        source = (ROOT / "setup").read_text()
        marker = 'if ! [ $# = 0 ]; then\n'
        self.assertEqual(1, source.count(marker))
        (self.checkout / "setup").write_text(source.replace(
            marker, '. "$NVIM_SETUP_FIXTURE"\n' + marker, 1,
        ))
        self.clones = self.directory / "clones"
        self.starts = self.directory / "starts"
        self.env = os.environ | {
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.directory / "custom data"),
            "NVIM_SETUP_FIXTURE": str(ROOT / "tests/setup/fixtures/nvim-local-setup.sh"),
            "NVIM_SETUP_CLONES": str(self.clones),
            "NVIM_SETUP_STARTS": str(self.starts),
            "NVIM_SETUP_CLONE_STATUS": "0",
            "NVIM_SETUP_START_STATUS": "0",
            "SETUP_NONINTERACTIVE": "1",
        }

    def run_setup(self, option="local"):
        return subprocess.run(
            ["sh", str(self.checkout / "setup"), option],
            env=self.env, cwd=self.checkout, text=True, capture_output=True, timeout=10,
        )

    def test_local_package_options_install_lazy_once_before_starting_neovim(self):
        for option in ("local", "install-local", "6"):
            with self.subTest(option=option):
                result = self.run_setup(option)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        destination = Path(self.env["XDG_DATA_HOME"]) / "nvim/lazy/lazy.nvim"
        self.assertTrue((destination / "lua/lazy/init.lua").is_file())
        self.assertEqual([str(destination)], self.clones.read_text().splitlines())
        self.assertEqual(["startup"], self.starts.read_text().splitlines())

    def test_clone_failure_fails_local_setup_without_starting_neovim(self):
        self.env["NVIM_SETUP_CLONE_STATUS"] = "17"
        result = self.run_setup()
        self.assertEqual(17, result.returncode, result.stdout + result.stderr)
        self.assertFalse(self.starts.exists())

    def test_neovim_failure_fails_local_setup(self):
        self.env["NVIM_SETUP_START_STATUS"] = "19"
        result = self.run_setup()
        self.assertEqual(19, result.returncode, result.stdout + result.stderr)
        self.assertEqual(["startup"], self.starts.read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
