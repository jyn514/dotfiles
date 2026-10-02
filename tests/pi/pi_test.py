#!/usr/bin/env python3

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin/pi"


class PiWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        sandbox = self.root / "codex-sandbox"
        sandbox.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        sandbox.chmod(0o755)
        self.cli = self.root / ".local/share/pi/node/node_modules/.bin/pi"
        self.cli.parent.mkdir(parents=True)
        self.cli.symlink_to(ROOT / "tests/pi/export_fixture.py")
        # Installed command links must resolve back to the owning checkout.
        self.wrapper = self.root / "pi"
        self.wrapper.symlink_to(WRAPPER)
        self.environment = {**os.environ, "HOME": str(self.root),
                            "PATH": f"{self.root}:{os.environ['PATH']}"}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_wrapper(self, *arguments: str) -> list[str]:
        return subprocess.run(
            [str(self.wrapper), *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            env=self.environment,
        ).stdout.splitlines()

    def test_normal_session_delegates_to_sandbox(self) -> None:
        self.assertEqual(["prompt"], self.run_wrapper("prompt"))

    def test_export_writes_requested_file_without_starting_sandbox(self) -> None:
        source = self.root / "session with spaces.jsonl"
        source.write_text("Session content")
        output = self.root / "export with spaces.html"
        self.assertEqual([f"Exported to: {output}"],
                         self.run_wrapper("--export", str(source), str(output)))
        self.assertEqual("<html>Session content</html>", output.read_text())
        self.assertEqual("Session content", source.read_text())

    def test_export_without_destination_keeps_native_default(self) -> None:
        source = self.root / "session.jsonl"
        source.write_text("Session content")
        result = subprocess.run(
            [str(self.wrapper), "--export", str(source)], cwd=self.root,
            env=self.environment, capture_output=True, text=True, check=True,
        )
        self.assertEqual("Exported to: pi-session-session.html\n", result.stdout)
        self.assertEqual("<html>Session content</html>",
                         (self.root / "pi-session-session.html").read_text())

    def test_native_export_failure_keeps_exit_status_without_sandbox_fallback(self) -> None:
        result = subprocess.run(
            [str(self.wrapper), "--export", "session.jsonl", "output.html"],
            cwd=self.root, env={**self.environment, "PI_EXPORT_FIXTURE_FAIL": "1"},
            capture_output=True, text=True,
        )
        self.assertEqual(7, result.returncode)
        self.assertEqual("Native export refused\n", result.stderr)
        self.assertEqual("", result.stdout)
        self.assertFalse((self.root / "output.html").exists())

    def test_missing_native_pi_fails_without_starting_sandbox(self) -> None:
        self.cli.unlink()
        result = subprocess.run(
            [str(self.wrapper), "--export", "session.jsonl"], env=self.environment,
            capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Host Pi is not installed", result.stderr)
        self.assertEqual("", result.stdout)

    def test_export_requires_exact_nonempty_operands_before_invoking_native_pi(self) -> None:
        for operands in ([], [""], ["session.jsonl", ""],
                         ["session.jsonl", "--export", "", "--print", "host prompt"]):
            with self.subTest(operands=operands):
                result = subprocess.run(
                    [str(self.wrapper), "--export", *operands],
                    env={**self.environment, "PI_EXPORT_FIXTURE_FAIL": "1"},
                    capture_output=True, text=True,
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn("Usage: pi --export", result.stderr)
                self.assertNotIn("Native export refused", result.stderr)
                self.assertEqual("", result.stdout)

    def test_export_after_prompt_separator_still_uses_sandbox(self) -> None:
        self.assertEqual(["--", "--export", "a prompt"],
                         self.run_wrapper("--", "--export", "a prompt"))

    @unittest.skipUnless(shutil.which("bb"), "requires Babashka")
    def test_extract_chat_batch_native_writes_relative_receipts_directory(self) -> None:
        source_dir = self.root / "sessions"
        source_dir.mkdir()
        for name in ("one", "two"):
            (source_dir / f"{name}.jsonl").write_text(
                json.dumps({"type": "session", "version": 3, "id": name}) + "\n"
            )
        result = subprocess.run(
            ["bb", str(ROOT / "tools/extract-chat/extract-chat"),
             "--extract-dir", "receipts", str(source_dir), "--native"],
            cwd=self.root, env=self.environment, capture_output=True, text=True, check=True,
        )
        receipts = self.root / "receipts"
        self.assertEqual(["one.html", "two.html"], sorted(path.name for path in receipts.iterdir()))
        for name in ("one", "two"):
            source = source_dir / f"{name}.jsonl"
            output = receipts / f"{name}.html"
            self.assertEqual(f"<html>{source.read_text()}</html>", output.read_text())
            self.assertIn(str(output), result.stdout)
        self.assertFalse((self.root / "pi-session-one.html").exists())

    def test_one_shot_commands_remain_first_argument(self) -> None:
        for command in ("auth", "config", "install", "list", "remove", "uninstall", "update"):
            with self.subTest(command=command):
                self.assertEqual([command], self.run_wrapper(command))


if __name__ == "__main__":
    unittest.main()
