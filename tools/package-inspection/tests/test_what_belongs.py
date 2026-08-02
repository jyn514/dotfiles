import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/what-belongs"


class WhatBelongsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, body: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def run_command(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(COMMAND), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": str(self.directory)},
            check=False,
        )

    def test_debian_query_preserves_output_and_exact_package_arguments(self) -> None:
        calls = self.directory / "calls"
        self.executable(
            "dpkg",
            f'printf "%s\\0" "$@" > "{calls}"\n'
            "printf '/ordinary\\n/path with spaces\\n'\n",
        )
        self.executable("rpm", "exit 99\n")

        result = self.run_command("package one", "-opaque")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"/ordinary\n/path with spaces\n", result.stdout)
        self.assertEqual(b"-L\0--\0package one\0-opaque\0", calls.read_bytes())

    def test_rpm_is_used_when_dpkg_is_missing(self) -> None:
        calls = self.directory / "calls"
        self.executable(
            "rpm",
            f'printf "%s\\0" "$@" > "{calls}"\n'
            "printf '/rpm/path\\n'\n",
        )

        result = self.run_command("tea")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"/rpm/path\n", result.stdout)
        self.assertEqual(b"-ql\0--\0tea\0", calls.read_bytes())

    def test_manager_failure_and_partial_output_are_propagated(self) -> None:
        self.executable("dpkg", "printf '/partial\\n'\nprintf 'query failed\\n' >&2\nexit 23\n")

        result = self.run_command("tea")

        self.assertEqual(23, result.returncode)
        self.assertEqual(b"/partial\n", result.stdout)
        self.assertEqual(b"query failed\n", result.stderr)

    def test_empty_success_and_missing_manager_are_distinct(self) -> None:
        self.executable("dpkg", "exit 0\n")
        empty = self.run_command("tea")
        (self.directory / "dpkg").unlink()
        missing = self.run_command("tea")

        self.assertEqual(0, empty.returncode)
        self.assertEqual(b"", empty.stdout)
        self.assertEqual(1, missing.returncode)
        self.assertEqual(b"no supported package manager found\n", missing.stderr)


if __name__ == "__main__":
    unittest.main()
