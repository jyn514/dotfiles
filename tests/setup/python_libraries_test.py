#!/usr/bin/env python3
"""Run the real setup/pip path offline with a disposable user package directory."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "posix", "tests the POSIX setup entrypoint")
class SystemPythonLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.directory = Path(self.tempdir.name)
        self.checkout = self.directory / "checkout"
        for relative in ("setup", "lib/shell/lib.sh", "lib/shell/env.sh"):
            target = self.checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        self.home = self.directory / "home"
        self.home.mkdir()
        self.userbase = self.home / "python-user"
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        # The test runner may use a venv, which disables user-site imports.
        # Exercise its base interpreter, like the normal system Python command.
        self.python = sys._base_executable
        (self.bin / "python3").symlink_to(self.python)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")} | {
            "HOME": str(self.home),
            "PYTHONUSERBASE": str(self.userbase),
            "PYTHONNOUSERSITE": "",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
        }
        self.env.pop("PYTHONPATH", None)
        self.env.pop("PYTHONHOME", None)
        # A tiny local wheel exercises pip's actual user-site behavior without
        # downloading or modifying any real packages or checked-in artifacts.
        self.wheel = self.directory / "dotfiles_runtime_probe-1.0-py3-none-any.whl"
        dist = "dotfiles_runtime_probe-1.0.dist-info"
        with zipfile.ZipFile(self.wheel, "w") as wheel:
            wheel.writestr("dotfiles_runtime_probe.py", (ROOT / "tests/setup/fixtures/runtime_probe.py").read_bytes())
            wheel.writestr(f"{dist}/METADATA", "Metadata-Version: 2.1\nName: dotfiles-runtime-probe\nVersion: 1.0\n")
            wheel.writestr(f"{dist}/WHEEL", "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            wheel.writestr(f"{dist}/RECORD", "")
        self.manifest = self.checkout / "install/python.txt"
        self.manifest.parent.mkdir()
        self.manifest.write_text(str(self.wheel) + "\n")

    def setup_python(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.checkout / "setup"), "py"], cwd=self.checkout, env=self.env,
            text=True, capture_output=True, check=False, timeout=30,
        )

    def test_setup_installs_into_system_pythons_user_site_and_a_fresh_process_imports_it(self) -> None:
        result = self.setup_python()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        result = subprocess.run(
            [self.python, "-c",
             "import dotfiles_runtime_probe as p, sys, json; print(json.dumps([sys.executable, p.__file__, p.VALUE]))"],
            env=self.env, text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        executable, installed_file, value = json.loads(result.stdout)
        self.assertEqual(self.python, executable)
        self.assertTrue(Path(installed_file).is_relative_to(self.userbase), installed_file)
        self.assertEqual("system-python-runtime", value)
        # Repeating setup must not select a different interpreter or damage the install.
        result = self.setup_python()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_requirement_fails_setup_without_installing_a_fallback(self) -> None:
        self.manifest.write_text(str(self.directory / "missing-1.0-py3-none-any.whl") + "\n")
        result = self.setup_python()
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("missing", result.stderr)
        self.assertFalse(list(self.userbase.rglob("dotfiles_runtime_probe.py")))


if __name__ == "__main__":
    unittest.main()
