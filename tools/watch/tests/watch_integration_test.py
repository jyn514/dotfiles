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


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_watch_displays_failed_command_before_next_iteration(self) -> None:
        mocks = self.directory / "mocks"
        mocks.mkdir()
        runner = self.directory / "runinpty.py"
        runner.write_text("#!/bin/sh\nprintf 'failed output'\nexit 7\n")
        runner.chmod(0o755)
        for name, contents in (
            ("clear", "exit 0\n"),
            ("tput", "exit 0\n"),
            ("sleep", "exit 31\n"),
        ):
            executable = mocks / name
            executable.write_text("#!/bin/sh\n" + contents)
            executable.chmod(0o755)

        result = subprocess.run(
            [str(ROOT / "bin/watch"), "command"],
            env=os.environ
            | {
                "PATH": f"{mocks}:{os.environ['PATH']}",
                "WATCH_RUNNER": str(runner),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(31, result.returncode)
        self.assertEqual("failed output\n[exit 7]", result.stdout)


if __name__ == "__main__":
    unittest.main()
