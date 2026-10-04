import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "libexec/agent-wrappers/codex-rename"
FIXTURE = Path(__file__).with_name("codex_app_server_fixture.py")


class CodexRenameTest(unittest.TestCase):
    def run_command(self, directory, title, thread_id="owned-session", failure=None):
        environment = {**os.environ, "CODEX_HOME": str(directory),
                       "PATH": str(directory), "RENAME_FAILURE": failure or ""}
        environment.pop("CODEX_THREAD_ID", None)
        if thread_id:
            environment["CODEX_THREAD_ID"] = thread_id
        return subprocess.run([shutil.which("python3"), str(COMMAND), title], env=environment,
                              text=True, capture_output=True, timeout=8)

    def exercise_server(self, title="rename π " + "x" * 150, failure=None):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            # Reach the real dotfiles wrapper, with a native fixture behind it.
            (home / "codex").symlink_to(ROOT / "bin/codex")
            native = home / "native"
            native.mkdir()
            launcher = native / "codex"
            launcher.write_text("#!" + shutil.which("python3") + "\n" + FIXTURE.read_text().split("\n", 1)[1])
            launcher.chmod(0o755)
            environment = {**os.environ, "CODEX_HOME": directory,
                           "CODEX_THREAD_ID": "owned-session",
                           "RENAME_FAILURE": failure or "",
                           "PATH": str(home) + ":" + str(native) + ":" + os.environ["PATH"]}
            result = subprocess.run([str(COMMAND), title], env=environment,
                                    text=True, capture_output=True, timeout=8)
            requests = [json.loads(line) for line in (home / "requests").read_text().splitlines()]
            pid = int((home / "pid").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            self.assertFalse((home / "rules").exists())
            self.assertFalse((home / "config.toml").exists())
            return result, requests

    def test_renames_current_session_and_verifies_unicode_long_title(self):
        result, requests = self.exercise_server()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("(verified)", result.stdout)
        self.assertEqual(["initialize", "initialized", "thread/read", "thread/name/set", "thread/read"],
                         [request["method"] for request in requests])
        self.assertIn("rename π", result.stdout)

    def test_failed_read_does_not_send_name_update(self):
        result, requests = self.exercise_server(failure="read-error")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("session missing", result.stderr)
        self.assertIn("name update was not sent", result.stderr)
        self.assertNotIn("thread/name/set", [request["method"] for request in requests])

    def test_mismatching_read_back_reports_unverified_update(self):
        result, _ = self.exercise_server(failure="mismatch")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("read-back name differs", result.stderr)
        self.assertIn("name update is unverified", result.stderr)

    def test_disconnect_during_update_does_not_claim_success(self):
        result, _ = self.exercise_server(failure="disconnect")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("name update is unverified", result.stderr)

    def test_missing_session_id_and_invalid_titles_fail_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_command(directory, "title", thread_id=None)
            self.assertIn("CODEX_THREAD_ID is unset", result.stderr)
            self.assertEqual(2, result.returncode)
            for title in ("", "\nmultiline", "  "):
                result = self.run_command(directory, title)
                self.assertEqual(2, result.returncode)
                self.assertIn("nonempty single line", result.stderr)

    def test_missing_codex_reports_no_update_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_command(directory, "title")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("starting a temporary Codex app-server failed", result.stderr)
        self.assertIn("name update was not sent", result.stderr)
        self.assertIn("check that codex app-server can start", result.stderr)

    def test_child_that_ignores_eof_is_terminated(self):
        result, _ = self.exercise_server(failure="linger")
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
