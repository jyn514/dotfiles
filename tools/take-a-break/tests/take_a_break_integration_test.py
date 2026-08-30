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

    def test_take_a_break_matches_the_window_pid_field(self) -> None:
        calls = self.directory / "wmctrl-calls"
        dialog_pid = self.directory / "dialog-pid"
        self.executable("zenity", 'printf "%s\\n" "$$" > "$DIALOG_PID"\n')
        self.executable(
            "wmctrl",
            'if [ "$1" = -l ]; then\n'
            '  pid=$(cat "$DIALOG_PID")\n'
            '  printf "0xwrong 0 999 host title-%s\\n" "$pid"\n'
            '  printf "0xright 0 %s host title\\n" "$pid"\n'
            "else\n"
            '  printf "%s\\n" "$*" > "$WMCTRL_CALLS"\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/take-a-break")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "DIALOG_PID": str(dialog_pid),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "WMCTRL_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("-i -r 0xright -b add,above\n", calls.read_text())


if __name__ == "__main__":
    unittest.main()
