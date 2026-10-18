"""Exercise paginated repair and the installed Codex consumer."""
import fcntl
import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/codex-import"


class CodexImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "codex home's state"
        self.home.mkdir()
        self.fake_bin = Path(temporary.name) / "bin"
        self.fake_bin.mkdir()
        (self.fake_bin / "codex").symlink_to(Path(__file__).parent / "fixtures/codex-import-cli")
        self.environment = dict(os.environ, CODEX_HOME=str(self.home),
                                PATH=f"{self.fake_bin}:{os.environ['PATH']}")

    def run_command(self):
        return subprocess.run([str(COMMAND)], env=self.environment, capture_output=True,
                              text=True, timeout=40)

    def test_pages_both_archives_with_live_writer_and_without_resetting_state(self):
        database = self.home / "state_5.sqlite"
        database.write_bytes(b"owned state must not be opened directly")
        locks = self.home / "thread-writer-locks"
        locks.mkdir()
        with (locks / "active.lock").open("wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for _ in range(2):
                result = self.run_command()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("Session import complete. Scanned 4 sessions.", result.stdout)
        self.assertEqual(b"owned state must not be opened directly", database.read_bytes())
        requests = [json.loads(line) for line in (self.home / "requests.jsonl").read_text().splitlines()]
        pages = [r["params"] for r in requests if r["method"] == "thread/list"]
        self.assertEqual([(False, None), (False, "page-2"), (True, None), (True, "page-2")] * 2,
                         [(p["archived"], p["cursor"]) for p in pages])
        for page in pages:
            self.assertFalse(page["useStateDbOnly"])
            self.assertEqual([], page["modelProviders"])
            self.assertIn("exec", page["sourceKinds"])
            self.assertIn("subAgentThreadSpawn", page["sourceKinds"])
        self.assertEqual([], list(self.home.glob("state_5.before-reimport.*")))

    def test_failures_report_partial_repairs_and_allow_retry(self):
        for mode in ("exit", "rpc-error", "malformed", "repeat"):
            with self.subTest(mode=mode):
                self.environment["CODEX_IMPORT_TEST_MODE"] = mode
                result = self.run_command()
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("Session import complete", result.stdout)
                self.assertIn("retry codex-import", result.stderr)
                del self.environment["CODEX_IMPORT_TEST_MODE"]
                self.assertEqual(0, self.run_command().returncode)

    def test_installed_codex_repairs_synced_rollouts_without_changing_transcripts(self):
        real_path = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep)
                                   if Path(p).resolve() != (ROOT / "bin").resolve())
        real = os.environ.get("DOTFILES_TEST_CODEX_REAL") or shutil.which("codex", path=real_path)
        if real is None:
            self.skipTest("Codex CLI is not installed")
        (self.fake_bin / "codex").unlink()
        (self.fake_bin / "codex").symlink_to(Path(real).resolve())
        self.environment["DOTFILES_SANDBOX"] = "1"
        self.environment["PATH"] = f"{ROOT / 'bin'}:{self.environment['PATH']}"
        initialized = subprocess.run([real, "app-server", "--stdio"], env=self.environment,
                                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            marker = db.execute("SELECT * FROM backfill_state").fetchall()
        originals = {}
        ids = []
        for archived in (False, True):
            # More than a page, including same-timestamp IDs, must all be repaired.
            for index in range(103):
                source = ("cli", "exec", {"subagent": "review"})[index % 3]
                sid = str(uuid.uuid4())
                ids.append(sid)
                directory = self.home / ("archived_sessions" if archived else "sessions/2026/01/01")
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"rollout-2026-01-01T10-00-00-{sid}.jsonl"
                stamp = "2026-01-01T10:00:00Z"
                events = [
                    {"type": "session_meta", "payload": {"id": sid, "timestamp": stamp,
                     "cwd": str(self.home), "originator": "codex_cli_rs", "cli_version": "0.162.1",
                     "source": source, "model_provider": "different-provider"}},
                    {"type": "response_item", "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "synced session"}]}},
                    {"type": "event_msg", "payload": {"type": "user_message", "message": "synced session",
                     "images": [], "local_images": [], "text_elements": []}},
                ]
                if index % 2:
                    events[0]["payload"]["history_mode"] = "paginated"
                    for ordinal, event in enumerate(events):
                        event["ordinal"] = ordinal
                path.write_text("".join(json.dumps(dict(event, timestamp=stamp)) + "\n" for event in events))
                originals[path] = path.read_bytes()
        # Keep a real second process holding a loaded thread throughout repair.
        active = subprocess.Popen([real, "app-server", "--stdio"], env=self.environment,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
        def cleanup():
            active.terminate()
            try:
                active.wait(timeout=5)
            except subprocess.TimeoutExpired:
                active.kill()
                active.wait()
            active.stdin.close()
            active.stdout.close()
        self.addCleanup(cleanup)
        replies = queue.Queue()
        def read():
            for line in active.stdout:
                replies.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        def rpc(request_id, method, params):
            active.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
            active.stdin.flush()
            while True:
                reply = replies.get(timeout=25)
                if "method" not in reply and reply.get("id") == request_id:
                    self.assertNotIn("error", reply)
                    return reply["result"]
        rpc(1, "initialize", {"clientInfo": {"name": "import_test", "version": "1"}})
        rpc(2, "thread/resume", {"threadId": ids[0], "excludeTurns": True, "modelProvider": "openai"})
        # The active writer may append resume metadata; only unloaded transcripts
        # have a fixed byte-for-byte expectation during concurrent repair.
        active_path = next(path for path in originals if ids[0] in path.name)
        originals.pop(active_path)
        # Remove unloaded rows so startup backfill cannot satisfy the repair assertion.
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("DELETE FROM threads WHERE id != ?", (ids[0],))
        for _ in range(2):
            result = self.run_command()
            self.assertEqual(0, result.returncode, result.stderr)
            with sqlite3.connect(self.home / "state_5.sqlite") as db:
                self.assertEqual(set(ids), {row[0] for row in db.execute("SELECT id FROM threads")})
                self.assertEqual(marker, db.execute("SELECT * FROM backfill_state").fetchall())
            for path, original in originals.items():
                self.assertEqual(original, path.read_bytes())
        self.assertEqual([], list(self.home.glob("state_5.before-reimport.*")))
        self.assertIsNone(active.poll())
        self.assertEqual(ids[0], rpc(3, "thread/read", {"threadId": ids[0]})["thread"]["id"])


if __name__ == "__main__":
    unittest.main()
