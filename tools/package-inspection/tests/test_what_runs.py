import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/what-runs"


class WhatRunsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def manager(self, name: str, output: bytes, status: int = 0) -> None:
        path = self.directory / name
        source = (
            f"#!{sys.executable}\n"
            "import sys\n"
            f"sys.stdout.buffer.write({output!r})\n"
            f"raise SystemExit({status})\n"
        )
        path.write_text(source)
        path.chmod(0o755)

    def run_command(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(COMMAND), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": str(self.directory)},
            check=False,
        )

    def test_filters_bytes_paths_and_preserves_symlink_names(self) -> None:
        root = os.fsencode(self.directory)
        executable = root + b"/ordinary executable"
        leading = root + b"/-leading"
        undecodable = root + b"/invalid-\xff"
        linked = root + b"/linked executable"
        plain = root + b"/not executable"
        directory = root + b"/directory"
        for path, mode in ((executable, 0o755), (leading, 0o755), (undecodable, 0o755), (plain, 0o644)):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT, mode)
            os.close(descriptor)
            os.chmod(path, mode)
        os.mkdir(directory)
        os.symlink(executable, linked)
        records = (plain, executable, directory, leading, linked, undecodable, root + b"/missing")
        self.manager("dpkg", b"\n".join(records))

        result = self.run_command("package with spaces")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"\n".join((executable, leading, linked, undecodable)) + b"\n", result.stdout)

    def test_rpm_output_is_filtered_when_dpkg_is_absent(self) -> None:
        executable = self.directory / "rpm executable"
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
        self.manager("rpm", os.fsencode(executable) + b"\n")

        result = self.run_command("tea")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(os.fsencode(executable) + b"\n", result.stdout)

    def test_partial_query_output_is_discarded_on_failure(self) -> None:
        executable = self.directory / "partial executable"
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
        self.manager("dpkg", os.fsencode(executable) + b"\n", status=31)

        result = self.run_command("tea")

        self.assertEqual(31, result.returncode)
        self.assertEqual(b"", result.stdout)

    def test_empty_query_and_missing_manager_are_distinct(self) -> None:
        self.manager("dpkg", b"")
        empty = self.run_command("tea")
        (self.directory / "dpkg").unlink()
        missing = self.run_command("tea")

        self.assertEqual(0, empty.returncode)
        self.assertEqual(b"", empty.stdout)
        self.assertEqual(1, missing.returncode)
        self.assertEqual(b"no supported package manager found\n", missing.stderr)


if __name__ == "__main__":
    unittest.main()
