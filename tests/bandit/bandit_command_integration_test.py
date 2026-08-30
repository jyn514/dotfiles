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

    def test_bandit_preserves_spaces_and_hyphens_in_password(self) -> None:
        calls = self.directory / "sshpass-calls"
        (self.directory / "bandit.txt").write_text("7 - tea time-with-hyphens\n")
        self.executable("sshpass", 'printf "<%s>\\n" "$@" > "$SSHPASS_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/bandit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "SSHPASS_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "<-p>\n<tea time-with-hyphens>\n<ssh>\n<-p>\n<2220>\n"
            "<bandit7@bandit.labs.overthewire.org>\n",
            calls.read_text(),
        )


if __name__ == "__main__":
    unittest.main()
