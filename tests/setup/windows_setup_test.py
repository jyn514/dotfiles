#!/usr/bin/env python3

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class WindowsSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.setup = (ROOT / "setup.ps1").read_text()

    def test_installs_mise_with_winget(self) -> None:
        self.assertIn('Install-WingetPackage "jdx.mise"', self.setup)
        self.assertIn("mise install --yes", self.setup)
        self.assertIn("mise reshim", self.setup)

    def test_uses_shared_locked_mise_configuration(self) -> None:
        self.assertIn('"config\\mise.toml"', self.setup)
        self.assertIn("MISE_GLOBAL_CONFIG_FILE", self.setup)
        self.assertNotIn("cargo binstall", self.setup)
        self.assertNotIn("rustup toolchain", self.setup)

    def test_uses_shared_python_manifest_through_mise(self) -> None:
        self.assertIn('"install\\python.txt"', self.setup)
        self.assertIn("mise exec -- python -m pip install", self.setup)
        self.assertNotIn("Get-Content rust.txt", self.setup)

    def test_adds_windows_mise_shims_to_path_idempotently(self) -> None:
        self.assertIn('"mise\\shims"', self.setup)
        self.assertIn("if ($Entries -notcontains $NewPath)", self.setup)


if __name__ == "__main__":
    unittest.main()
