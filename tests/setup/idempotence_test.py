#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SetupIdempotenceTests(unittest.TestCase):
    def test_global_setup_prints_sudo_before_running_and_preserves_io_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            binaries = directory / "bin"
            binaries.mkdir()
            for name in ("id", "bb", "sudo"):
                (binaries / name).symlink_to(ROOT / "tests/setup/elevation_fixture.sh")
            environment = os.environ | {
                "PATH": f"{binaries}:{os.environ['PATH']}",
                "PACKAGE_PLAN_BB": str(binaries / "bb"),
                "SUDO_TEST_STATUS": "17",
            }
            result = subprocess.run(["./setup", "7"], cwd=ROOT, env=environment,
                                    input="input passes through\n", text=True,
                                    capture_output=True, check=False)
            self.assertEqual(17, result.returncode, result.stderr)
            self.assertEqual([
                "setup: elevated command: sudo --preserve-env=PATH ./libexec/setup/setup_sudo.sh main",
                "fixture: sudo is running",
            ], result.stderr.splitlines())
            self.assertTrue(result.stdout.endswith(
                "--preserve-env=PATH\n./libexec/setup/setup_sudo.sh\nmain\ninput passes through\n"))

    def test_backup_option_routes_to_native_scheduler_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            home = directory / "home"
            binaries = directory / "bin"
            home.mkdir()
            binaries.mkdir()
            log = directory / "installer-calls"
            python = binaries / "python3"
            python.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$INSTALLER_CALLS"\n'
            )
            python.chmod(0o755)
            env = os.environ.copy()
            env.update(
                INSTALLER_CALLS=str(log),
                HOME=str(home),
                PATH=f"{binaries}:{env['PATH']}",
            )

            results = [
                subprocess.run(
                    ["./setup", "5"],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                for _ in range(2)
            ]

            for result in results:
                self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["tools/backup/install.py"] * 2, log.read_text().splitlines())

    def test_kde_keybinding_patch_accepts_an_already_applied_patch(self) -> None:
        setup = (ROOT / "setup").read_text()

        self.assertIn("patch --forward --silent", setup)
        self.assertIn("patch --reverse --dry-run --silent", setup)


if __name__ == "__main__":
    unittest.main()
