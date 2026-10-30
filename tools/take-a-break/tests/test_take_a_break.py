from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/take-a-break"
MODULE_PATH = Path(__file__).resolve().parents[1] / "take_a_break/main.py"
SPEC = importlib.util.spec_from_file_location("take_a_break_main", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
take_a_break = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(take_a_break)


class TakeABreakTests(unittest.TestCase):
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

    def environment(self) -> dict[str, str]:
        return os.environ | {
            "CALLS": str(self.calls),
            "CLIENT_MACHINE": take_a_break.socket.gethostname(),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

    def test_pid_parser_requires_the_client_machine_and_pid_columns(self) -> None:
        output = (
            b"0xremote 0 42 remote title\n"
            b"0xwrong 0 999 local title-42\n"
            b"0xright 0 42 local title\n"
        )
        self.assertEqual(b"0xright", take_a_break.window_for_pid(output, 42, b"local"))
        self.assertEqual(b"0xremote", take_a_break.window_for_pid(output, 42, b"remote"))
        self.assertIsNone(take_a_break.window_for_pid(output, 7, b"local"))
        self.assertIsNone(take_a_break.window_for_pid(output, 42, b"other"))

    def test_pid_parser_does_not_infer_a_missing_or_partial_client_machine(self) -> None:
        for output in (b"0xmissing 0 42\n", b"0xpartial 0 42 local.example title\n"):
            with self.subTest(output=output):
                self.assertIsNone(take_a_break.window_for_pid(output, 42, b"local"))

    def test_interrupt_terminates_and_reaps_the_owned_dialog(self) -> None:
        dialog = Mock()
        with patch.object(take_a_break.subprocess, "Popen", return_value=dialog), patch.object(
            take_a_break.time, "sleep", side_effect=KeyboardInterrupt
        ):
            self.assertEqual(130, take_a_break.main([]))
        dialog.terminate.assert_called_once_with()
        dialog.wait.assert_called_once_with()

    def test_passes_exact_dialog_and_window_arguments(self) -> None:
        pid_file = self.directory / "pid"
        self.executable(
            "zenity",
            'printf "zenity" >> "$CALLS"\n'
            'for value in "$@"; do printf " <%s>" "$value" >> "$CALLS"; done\n'
            'printf "\\n" >> "$CALLS"\n'
            f'printf "%s\\n" "$$" > "{pid_file}"\n',
        )
        self.executable(
            "wmctrl",
            'if [ "$1" = -l ]; then\n'
            f'  pid=$(cat "{pid_file}")\n'
            '  printf "0xremote 0 %s remote.example title\\n" "$pid"\n'
            '  printf "0xright 0 %s %s title\\n" "$pid" "$CLIENT_MACHINE"\n'
            "else\n"
            '  printf "wmctrl" >> "$CALLS"\n'
            '  for value in "$@"; do printf " <%s>" "$value" >> "$CALLS"; done\n'
            '  printf "\\n" >> "$CALLS"\n'
            "fi\n",
        )

        result = subprocess.run(
            [COMMAND],
            env=self.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "zenity <--question> <--text=please> <--title=take a break> "
                "<--ok-label=i will> <--cancel-label=fuck you> <--modal>",
                "wmctrl <-i> <-r> <0xright> <-b> <add,above>",
            ],
            self.calls.read_text().splitlines(),
        )

    def test_dialog_status_wins_when_window_listing_fails(self) -> None:
        self.executable("zenity", "exit 17\n")
        self.executable("wmctrl", "exit 29\n")

        result = subprocess.run(
            [COMMAND],
            env=self.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(17, result.returncode)

    def test_missing_wmctrl_does_not_replace_the_dialog_status(self) -> None:
        dialog = Mock()
        dialog.wait.return_value = 17
        with patch.object(take_a_break.subprocess, "Popen", return_value=dialog), patch.object(
            take_a_break.subprocess, "run", side_effect=FileNotFoundError("wmctrl")
        ), patch.object(take_a_break.time, "sleep"), patch.object(take_a_break.sys, "stderr"):
            self.assertEqual(17, take_a_break.main([]))
        dialog.wait.assert_called_once_with()

    def test_failed_window_update_does_not_replace_the_dialog_status(self) -> None:
        self.executable("zenity", 'printf "%s\\n" "$$" > "$CALLS"\nexit 17\n')
        self.executable(
            "wmctrl",
            'if [ "$1" = -l ]; then\n'
            '  printf "0xright 0 %s %s title\\n" "$(cat "$CALLS")" "$CLIENT_MACHINE"\n'
            'else\n'
            '  exit 29\n'
            'fi\n',
        )
        result = subprocess.run([COMMAND], env=self.environment(), capture_output=True)
        self.assertEqual(17, result.returncode, result.stderr)

    def test_missing_zenity_is_a_dependency_error(self) -> None:
        (self.directory / "python3").symlink_to(sys.executable)
        environment = self.environment()
        environment["PATH"] = str(self.directory)

        result = subprocess.run(
            [COMMAND],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(127, result.returncode)
        self.assertIn(b"could not execute zenity", result.stderr)

    def test_installed_symlink_runs_from_another_directory(self) -> None:
        self.executable("zenity", "exit 0\n")
        self.executable("wmctrl", "exit 0\n")
        installed = self.directory / "installed-take-a-break"
        installed.symlink_to(COMMAND)

        result = subprocess.run(
            [installed],
            cwd="/",
            env=self.environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
