#!/usr/bin/env python3
"""Ordinary Pi children retain guest routing without retaining their parent's pane."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1]
ROOT = TOOL.parents[1]
WRAPPER = TOOL / "sandbox-host-pi"


class HostPiWrapperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        cli = self.home / ".local/share/pi/node/node_modules/.bin/pi"
        cli.parent.mkdir(parents=True)
        cli.symlink_to(TOOL / "tests/fixtures/host_pi_wrapper.py")
        self.environment = {
            **{key: value for key, value in os.environ.items()
               if not key.startswith("CODEX_SANDBOX_")}, "HOME": str(self.home),
            "CODEX_SANDBOX_TOOL_CONTAINER": "codex-sandbox-test-worker",
            "CODEX_SANDBOX_TOOL_CONNECT": "/trusted/tool-connect",
            "CODEX_SANDBOX_GUEST_CWD": "/src/example",
            "CODEX_SANDBOX_PI_OWNER": "/private/owner.sock",
            "CODEX_SANDBOX_PI_ATTACHMENT": "parent-attachment",
            "CODEX_SANDBOX_PI_OWNER_FD": "123",
            "CODEX_SANDBOX_CD_REQUEST": "/private/parent-cd.json",
            "CODEX_SANDBOX_PREVIOUS_CWD": "/old-parent-directory",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_wrapper(self, *arguments: str, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(WRAPPER), *arguments], env={**self.environment, **environment},
            capture_output=True, text=True, timeout=10,
        )

    def test_child_retains_guest_execution_without_independent_attachment(self) -> None:
        result = self.run_wrapper("--mode", "rpc", "--no-extensions", "--session", "child.jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        native = json.loads(result.stdout)
        self.assertEqual({
            "CODEX_SANDBOX_TOOL_CONTAINER": "codex-sandbox-test-worker",
            "CODEX_SANDBOX_TOOL_CONNECT": "/trusted/tool-connect",
            "CODEX_SANDBOX_GUEST_CWD": "/src/example",
        }, native["sandbox_environment"])
        self.assertEqual([
            "--extension", str(ROOT / "config/pi-agent/pi-extensions/index.ts"),
            "--extension", str(ROOT / "config/pi-agent/pi-extensions/guest-tools.ts"),
            "--mode", "rpc", "--no-extensions", "--session", "child.jsonl",
        ], native["arguments"])

    def test_export_remains_native_without_inheriting_pane_control(self) -> None:
        result = self.run_wrapper("--export", "session.jsonl", "out.html")
        self.assertEqual(0, result.returncode, result.stderr)
        native = json.loads(result.stdout)
        self.assertEqual(["--export", "session.jsonl", "out.html"], native["arguments"])
        self.assertNotIn("CODEX_SANDBOX_PI_OWNER", native["sandbox_environment"])
        self.assertNotIn("CODEX_SANDBOX_CD_REQUEST", native["sandbox_environment"])

    def test_native_child_exit_status_is_preserved(self) -> None:
        result = self.run_wrapper("--mode", "rpc", HOST_PI_FIXTURE_EXIT="17")
        self.assertEqual(17, result.returncode, result.stderr)

    def test_interactive_connection_failure_reports_once_without_traceback(self) -> None:
        result = self.run_wrapper("--sandbox-interactive")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual(1, len(result.stderr.splitlines()), result.stderr)
        self.assertIn("Host Pi attachment failed:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_export_cannot_start_an_interactive_attachment(self) -> None:
        result = self.run_wrapper("--sandbox-interactive", "--export", "session.jsonl")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Usage: pi --export", result.stderr)
        self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
