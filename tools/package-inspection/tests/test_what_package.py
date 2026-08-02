import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/what-package"


class WhatPackageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, body: str = "exit 0\n") -> Path:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def run_command(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(COMMAND), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": str(self.directory)},
            check=False,
        )

    def test_debian_query_resolves_symlink_and_preserves_additional_paths(self) -> None:
        target = self.executable("real tool")
        link = self.directory / "linked-tool"
        link.symlink_to(target)
        calls = self.directory / "calls"
        self.executable(
            "dpkg",
            f'printf "%s\\0" "$@" > "{calls}"\n'
            "printf 'package-name: canonical result\\n'\n",
        )
        self.executable("which", "exit 99\n")

        result = self.run_command("linked-tool", "path with spaces", "-opaque")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"package-name: canonical result\n", result.stdout)
        self.assertEqual(
            b"-S\0--\0" + os.fsencode(target.resolve()) + b"\0path with spaces\0-opaque\0",
            calls.read_bytes(),
        )

    def test_rpm_query_is_used_when_dpkg_is_missing(self) -> None:
        target = self.executable("tool")
        calls = self.directory / "calls"
        self.executable("rpm", f'printf "%s\\0" "$@" > "{calls}"\nprintf "rpm-package\\n"\n')

        result = self.run_command("tool")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"rpm-package\n", result.stdout)
        self.assertEqual(b"-qf\0--\0" + os.fsencode(target.resolve()) + b"\0", calls.read_bytes())

    def test_missing_executable_does_not_invoke_manager(self) -> None:
        called = self.directory / "called"
        self.executable("dpkg", f'touch "{called}"\n')

        result = self.run_command("missing-tool")

        self.assertEqual(127, result.returncode)
        self.assertFalse(called.exists())
        self.assertIn(b"executable not found", result.stderr)

    def test_missing_manager_and_manager_failure_are_distinct(self) -> None:
        self.executable("tool")
        missing = self.run_command("tool")
        self.executable("dpkg", "printf 'partial\\n'\nprintf 'failed\\n' >&2\nexit 26\n")
        failed = self.run_command("tool")

        self.assertEqual(1, missing.returncode)
        self.assertEqual(b"no supported package manager found\n", missing.stderr)
        self.assertEqual(26, failed.returncode)
        self.assertEqual(b"partial\n", failed.stdout)
        self.assertEqual(b"failed\n", failed.stderr)

    def test_no_arguments_reports_usage(self) -> None:
        result = self.run_command()

        self.assertEqual(2, result.returncode)
        self.assertIn(b"usage: what-package", result.stderr)


if __name__ == "__main__":
    unittest.main()
