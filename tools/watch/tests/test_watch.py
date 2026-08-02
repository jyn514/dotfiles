from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/watch"
MODULE_PATH = Path(__file__).resolve().parents[1] / "watch_command/main.py"
SPEC = importlib.util.spec_from_file_location("watch_command_main", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)


class WatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.calls = self.directory / "calls"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def executable(self, name: str, body: str) -> Path:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def environment(self, runner: Path) -> dict[str, str]:
        return os.environ | {
            "CALLS": str(self.calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "WATCH_RUNNER": str(runner),
        }

    def terminal_commands(self, sleep_status: int = 31) -> None:
        self.executable("clear", 'printf "clear <%s>\\n" "${1:-}" >> "$CALLS"\n')
        self.executable("tput", 'printf "tput <%s>\\n" "$1" >> "$CALLS"\n')
        self.executable(
            "sleep",
            f'printf "sleep <%s>\\n" "$1" >> "$CALLS"\nexit {sleep_status}\n',
        )

    def test_parses_attached_and_separate_options(self) -> None:
        self.assertEqual(
            watch.Options(".5", "bash", "printf two words"),
            watch.parse(["-n.5", "-x", "bash", "printf", "two words"], "sh"),
        )
        self.assertEqual(
            watch.Options("3", "zsh", "command"),
            watch.parse(["-n", "3", "-xzsh", "command"], "fish"),
        )
        with self.assertRaises(ValueError):
            watch.parse(["-n"], "sh")

    def test_buffers_output_and_passes_one_explicit_shell_command(self) -> None:
        self.terminal_commands()
        runner = self.executable(
            "runner",
            'printf "runner" >> "$CALLS"\n'
            'for value in "$@"; do printf " <%s>" "$value" >> "$CALLS"; done\n'
            'printf "\\n" >> "$CALLS"\n'
            'printf "output with trailing lines\\n\\n"\n'
            "exit 7\n",
        )

        result = subprocess.run(
            [COMMAND, "-n.25", "-x", "custom shell", "printf", "two words"],
            env=self.environment(runner),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(31, result.returncode, result.stderr)
        self.assertEqual(b"output with trailing lines\n[exit 7]", result.stdout)
        self.assertEqual(
            [
                "tput <smcup>",
                "clear <>",
                "runner <custom shell> <-c> <printf two words>",
                "clear <-x>",
                "sleep <.25>",
                "tput <rmcup>",
            ],
            self.calls.read_text().splitlines(),
        )

    def test_clear_failure_discards_the_completed_frame(self) -> None:
        count = self.directory / "clear-count"
        self.executable(
            "clear",
            f'if [ -e "{count}" ]; then exit 29; fi\ntouch "{count}"\n',
        )
        self.executable("tput", "exit 0\n")
        runner = self.executable("runner", "printf hidden\n")

        result = subprocess.run(
            [COMMAND, "command"],
            env=self.environment(runner),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(29, result.returncode)
        self.assertEqual(b"", result.stdout)

    def test_installed_symlink_runs_from_another_directory(self) -> None:
        self.terminal_commands()
        runner = self.executable("runner", "printf linked\n")
        installed = self.directory / "installed-watch"
        installed.symlink_to(COMMAND)
        self.assertEqual(ROOT / "libexec/runinpty.py", watch.DEFAULT_RUNNER)

        result = subprocess.run(
            [installed, "command"],
            cwd="/",
            env=self.environment(runner),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(31, result.returncode, result.stderr)
        self.assertEqual(b"linked", result.stdout)


if __name__ == "__main__":
    unittest.main()
