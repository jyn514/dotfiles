import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_git_backup_commands_do_not_overwrite_tar_output(self) -> None:
        calls = self.directory / "git-calls"
        self.executable("git", 'printf "%s\\n" "$*" >> "$GIT_CALLS"\n')

        for command in ("git-save", "git-backup"):
            with self.subTest(command=command):
                output = self.directory / command
                archive = Path(f"{output}.tar")
                archive.write_text("existing\n")
                result = subprocess.run(
                    [str(ROOT / f"bin/{command}"), "repository", str(output)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ | {
                        "GIT_CALLS": str(calls),
                        "PATH": f"{self.directory}:{os.environ['PATH']}",
                        "TMPDIR": str(self.directory),
                    },
                )

                self.assertEqual(1, result.returncode)
                self.assertEqual("existing\n", archive.read_text())
        self.assertFalse(calls.exists())


if __name__ == "__main__":
    unittest.main()
