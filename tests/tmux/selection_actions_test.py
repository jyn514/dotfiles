import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / "config/tmux"


class SelectionActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.calls = self.directory / "calls"
        self.environment = os.environ | {
            "PATH": str(self.directory),
            "ACTION_CALLS": str(self.calls),
        }
        (self.directory / "python3").symlink_to(sys.executable)
        for name in ("open", "hx-hax", "tmux", "dragon"):
            (self.directory / name).symlink_to(
                ROOT / "tests/tmux/fixtures/selection-command.py"
            )

    def run_helper(self, helper, *arguments, selection=b"", environment=None):
        return subprocess.run(
            [sys.executable, str(HELPERS / helper), *arguments],
            input=selection,
            capture_output=True,
            env=self.environment | (environment or {}),
            cwd=self.directory,
            check=False,
        )

    def test_open_and_hx_receive_exactly_one_path(self):
        for command in ("open", "hx-hax"):
            for path in (b"ordinary.md", b"odd ' $(touch injected)\ninvalid-\xff\n", b"-file"):
                with self.subTest(command=command, path=path):
                    result = self.run_helper("with-selection.py", command, selection=path)
                    self.assertEqual(0, result.returncode, result.stderr)
                    expected = b"./" + path if path.startswith(b"-") else path
                    self.assertEqual([os.fsdecode(expected)], json.loads(self.calls.read_text()))
                    self.assertFalse((self.directory / "injected").exists())

    def test_with_selection_preserves_command_arguments(self):
        result = self.run_helper("with-selection.py", "open", "--wait", selection=b"one file")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["--wait", "one file"], json.loads(self.calls.read_text()))

    def test_search_encodes_selection_as_one_query(self):
        result = self.run_helper(
            "search-selection.py", selection=b"odd ' $()\ninvalid-\xff\n"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["https://www.google.com/search?q=odd+%27+%24%28%29%0Ainvalid-%FF%0A"],
            json.loads(self.calls.read_text()),
        )

    def test_edit_types_quoted_editor_command_in_current_pane(self):
        payload = b"odd ' $(touch injected)\ninvalid-\xff\n"
        result = self.run_helper(
            "edit-selection.py", selection=payload,
            environment={"EDITOR": "editor --wait"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        arguments = json.loads(self.calls.read_text())
        self.assertEqual(["send-keys", "C-q", ";", "send-keys", "-l"], arguments[:5])
        self.assertEqual([";", "send-keys", "C-m"], arguments[6:])

        # Let the actual configured shell parse the injected command instead of
        # checking it with the same quoting library used by the helper.
        (self.directory / "editor").symlink_to(ROOT / "tests/tmux/fixtures/selection-command.py")
        for shell in ("/bin/sh", shutil.which("fish")):
            if shell is None:
                continue
            parsed = subprocess.run(
                [shell, "-c", arguments[5]], env=self.environment,
                cwd=self.directory, capture_output=True, check=False,
            )
            self.assertEqual(0, parsed.returncode, parsed.stderr)
            self.assertEqual(["--wait", os.fsdecode(payload)], json.loads(self.calls.read_text()))
            self.assertFalse((self.directory / "injected").exists())

    def test_edit_rejects_empty_or_malformed_editor_before_typing(self):
        for editor in ("", "unterminated '"):
            result = self.run_helper(
                "edit-selection.py", selection=b"file", environment={"EDITOR": editor}
            )
            self.assertEqual(2, result.returncode)
            self.assertFalse(self.calls.exists())

    def test_empty_selection_does_nothing(self):
        for helper, arguments in (
            ("with-selection.py", ["open"]),
            ("with-selection.py", ["hx-hax"]),
            ("edit-selection.py", []),
            ("search-selection.py", []),
        ):
            result = self.run_helper(helper, *arguments)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(self.calls.exists())

    def test_helpers_propagate_command_failures_and_report_missing_command(self):
        for helper, arguments, command in (
            ("with-selection.py", ["hx-hax"], "hx-hax"),
            ("edit-selection.py", [], "tmux"),
            ("search-selection.py", [], "open"),
        ):
            failed = self.run_helper(
                helper, *arguments, selection=b"file", environment={"ACTION_STATUS": "39"}
            )
            self.assertEqual(39, failed.returncode, failed.stderr)
            (self.directory / command).unlink()
            missing = self.run_helper(helper, *arguments, selection=b"file")
            self.assertEqual(127, missing.returncode)
            self.assertIn(command.encode(), missing.stderr)


if __name__ == "__main__":
    unittest.main()
