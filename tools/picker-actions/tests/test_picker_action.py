import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/picker-action"


class PickerActionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.calls = self.directory / "calls"

    def opener(self, status: int = 0) -> None:
        path = self.directory / "open"
        path.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\0" "$@" > "{self.calls}"\n'
            f"exit {status}\n"
        )
        path.chmod(0o755)

    def tmux(self, status: int = 0) -> None:
        path = self.directory / "tmux"
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "open(os.environ['TMUX_CALLS'], 'w').write(json.dumps(sys.argv[1:]))\n"
            f"raise SystemExit({status})\n"
        )
        path.chmod(0o755)

    def run_command(
        self,
        *arguments: str,
        selection: bytes = b"",
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        values = {"PATH": str(self.directory), "TMUX_CALLS": str(self.calls)}
        if environment:
            values.update(environment)
        return subprocess.run(
            [sys.executable, str(COMMAND), *arguments],
            input=selection,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=values,
            check=False,
        )

    def test_search_percent_encodes_one_opaque_nul_selection(self) -> None:
        self.opener()
        payload = b"odd ' $()\ninvalid-\xff"

        result = self.run_command("search", "--read0", selection=payload + b"\0")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            b"https://www.google.com/search?q=odd+%27+%24%28%29%0Ainvalid-%FF\0",
            self.calls.read_bytes(),
        )

    def test_direct_search_treats_leading_dash_as_text_after_separator(self) -> None:
        self.opener()

        result = self.run_command("search", "--", "-literal value")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            b"https://www.google.com/search?q=-literal+value\0",
            self.calls.read_bytes(),
        )

    def test_open_passes_multiple_nul_selections_as_opaque_arguments(self) -> None:
        self.opener()
        payload = b"relative path\0-line\nbreak\0invalid-\xff\0"

        result = self.run_command("open", "--read0", selection=payload)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            b"relative path\0./-line\nbreak\0invalid-\xff\0",
            self.calls.read_bytes(),
        )

    def test_open_propagates_launcher_failure(self) -> None:
        self.opener(status=39)

        result = self.run_command("open", "one", "two")

        self.assertEqual(39, result.returncode)

    def test_edit_sends_one_literal_quoted_command_sequence(self) -> None:
        self.tmux()
        payload = b"odd ' $(touch injected)\n-invalid-\xff"

        result = self.run_command(
            "edit",
            "--read0",
            selection=payload + b"\0",
            environment={"EDITOR": "editor --wait"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        expected_command = shlex.join(["editor", "--wait", os.fsdecode(payload)])
        self.assertEqual(
            [
                "send-keys",
                "C-q",
                ";",
                "send-keys",
                "-l",
                expected_command,
                ";",
                "send-keys",
                "C-m",
            ],
            json.loads(self.calls.read_text()),
        )

    def test_edit_validates_selection_and_editor_before_tmux(self) -> None:
        self.tmux()
        multiple = self.run_command("edit", "--read0", selection=b"one\0two\0")
        malformed_editor = self.run_command(
            "edit", "one", environment={"EDITOR": "unterminated '"}
        )

        self.assertEqual(2, multiple.returncode)
        self.assertEqual(2, malformed_editor.returncode)
        self.assertFalse(self.calls.exists())

    def test_edit_propagates_tmux_failure(self) -> None:
        self.tmux(status=40)

        result = self.run_command("edit", "selection")

        self.assertEqual(40, result.returncode)

    def test_empty_selection_is_cancellation(self) -> None:
        self.opener()
        for payload in (b"", b"\0"):
            result = self.run_command("search", "--read0", selection=payload)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(self.calls.exists())

    def test_multiple_and_malformed_selections_are_rejected(self) -> None:
        self.opener()
        for payload in (b"one\0two\0", b"one\0\0", b"unterminated"):
            result = self.run_command("search", "--read0", selection=payload)
            self.assertEqual(2, result.returncode)
            self.assertFalse(self.calls.exists())

    def test_missing_and_failed_launcher_are_propagated(self) -> None:
        missing = self.run_command("search", "tea")
        self.assertEqual(127, missing.returncode)
        self.assertEqual(b"open not found\n", missing.stderr)

        self.opener(status=38)
        failed = self.run_command("search", "tea")
        self.assertEqual(38, failed.returncode)

    def test_unknown_action_and_missing_selection_report_usage(self) -> None:
        unknown = self.run_command("unknown", "tea")
        missing = self.run_command("search")

        self.assertEqual(2, unknown.returncode)
        self.assertIn(b"unknown picker action", unknown.stderr)
        self.assertEqual(2, missing.returncode)
        self.assertIn(b"usage: picker-action search", missing.stderr)


if __name__ == "__main__":
    unittest.main()
