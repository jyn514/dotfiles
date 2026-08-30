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

    def test_tmux_cssh_uses_exact_window_names_and_labels_new_window_pane(self) -> None:
        calls = self.directory / "tmux-calls"
        created = self.directory / "window-created"
        self.executable(
            "tmux",
            'printf "<%s>\\n" "$@" >> "$TMUX_CALLS"\n'
            'case "$1" in\n'
            '  has-session) [ "$3" = current ];;\n'
            '  display-message) printf "current\\n";;\n'
            '  list-windows)\n'
            '    [ "${LIST_STATUS:-0}" -eq 0 ] || exit "$LIST_STATUS"\n'
            '    if [ -e "$WINDOW_CREATED" ]; then printf "cssh.-0\\n"; else printf "csshX-0\\n"; fi;;\n'
            '  new-window) touch "$WINDOW_CREATED"; printf "%%7\\n";;\n'
            '  split-window) printf "%%8\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "TMUX": "yes",
            "TMUX_CALLS": str(calls),
            "WINDOW_CREATED": str(created),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/tmux-cssh"), "-w", "-n", "cssh.", "first", "second"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        lines = calls.read_text().splitlines()
        self.assertIn("<%7>", lines)
        self.assertIn("<%8>", lines)
        pane_targets = [
            lines[index + 3]
            for index, line in enumerate(lines)
            if line == "<set-option>" and lines[index + 1] == "<-p>"
        ]
        self.assertEqual(["<%7>", "<%8>"], pane_targets)
    def test_tmux_cssh_propagates_window_query_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'printf "%s\\n" "$*" >> "$TMUX_CALLS"\n'
            'case "$1" in\n'
            '  has-session) exit 1;;\n'
            '  display-message) printf "current\\n";;\n'
            '  list-windows) exit 26;;\n'
            'esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/tmux-cssh"), "-w", "host"],
            env=os.environ
            | {
                "TMUX_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(26, result.returncode)
        self.assertNotIn("new-window", calls.read_text())


if __name__ == "__main__":
    unittest.main()
