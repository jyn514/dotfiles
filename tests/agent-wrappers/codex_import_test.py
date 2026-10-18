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

    def run_command(self, *arguments):
        return subprocess.run([str(COMMAND), *arguments], env=self.environment, capture_output=True,
                              text=True, timeout=40)

    def receipt_fixture(self):
        connection = sqlite3.connect(self.home / "state_5.sqlite")
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE threads (rollout_path TEXT PRIMARY KEY, archived INTEGER)")
        directory = self.home / "sessions/2026/01/01"
        directory.mkdir(parents=True)
        indexed = directory / "rollout-indexed.jsonl"
        indexed.write_text("indexed session\n")
        ignored = directory / "rollout-ignored.jsonl"
        ignored.write_text("native scanner excludes this file\n")
        connection.execute("INSERT INTO threads VALUES (?, 0)", (str(indexed),))
        connection.commit()
        return connection, indexed, ignored

    def assert_full_then_fast(self):
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Session import complete.", result.stdout)
        calls = (self.home / "requests.jsonl").read_bytes()
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("Session index is current.\n", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertEqual(calls, (self.home / "requests.jsonl").read_bytes())

    def test_receipt_reads_wal_and_allows_indexed_session_to_keep_growing(self):
        connection, indexed, ignored = self.receipt_fixture()
        self.assert_full_then_fast()
        indexed.write_text("active session appended another turn\n")
        self.assertEqual("Session index is current.\n", self.run_command().stdout)
        # Rows added by another live Codex process do not invalidate existing coverage.
        added = indexed.with_name("rollout-created-by-live-process.jsonl")
        added.write_text("already imported by its writer\n")
        connection.execute("INSERT INTO threads VALUES (?, 0)", (str(added),))
        connection.commit()
        self.assertEqual("Session index is current.\n", self.run_command().stdout)

    def test_new_changed_archived_and_removed_files_require_repair(self):
        _, indexed, ignored = self.receipt_fixture()
        self.assert_full_then_fast()
        added = ignored.with_name("rollout-newly-synced.jsonl")
        added.write_text("newly synced, not yet indexed\n")
        self.assert_full_then_fast()
        ignored.write_text("changed previously excluded file\n")
        self.assert_full_then_fast()
        archived = self.home / "archived_sessions"
        archived.mkdir()
        added.rename(archived / added.name)
        self.assert_full_then_fast()
        ignored.unlink()
        self.assert_full_then_fast()

    def test_database_loss_configuration_and_binary_changes_require_repair(self):
        connection, indexed, _ = self.receipt_fixture()
        self.assert_full_then_fast()
        connection.execute("DELETE FROM threads")
        connection.commit()
        self.assert_full_then_fast()
        (self.home / "config.toml").write_text('model = "another-model"\n')
        self.assert_full_then_fast()
        # Change which executable PATH resolves, without editing the shared fixture.
        fixture = Path(__file__).parent / "fixtures/codex-import-cli"
        (self.fake_bin / "codex").unlink()
        # A real new executable target must invalidate the binary fingerprint.
        subprocess.run(["cp", str(fixture), str(self.fake_bin / "codex")], check=True)
        subprocess.run(["cmp", str(fixture), str(self.fake_bin / "codex")], check=True)
        self.assert_full_then_fast()

    def test_changes_during_scan_and_unavailable_index_never_become_fast_hits(self):
        connection, _, ignored = self.receipt_fixture()
        self.environment["CODEX_IMPORT_TEST_CHANGE_DURING_SCAN"] = str(ignored)
        self.assertEqual(0, self.run_command().returncode)
        del self.environment["CODEX_IMPORT_TEST_CHANGE_DURING_SCAN"]
        self.assert_full_then_fast()
        connection.execute("DROP TABLE threads")
        connection.commit()
        for _ in range(2):
            result = self.run_command()
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("Session import complete.", result.stdout)
            self.assertFalse((self.home / "codex-import-receipt.json").exists())

    def test_failed_forced_scan_invalidates_receipt_and_allows_retry(self):
        self.receipt_fixture()
        self.assert_full_then_fast()
        self.environment["CODEX_IMPORT_TEST_MODE"] = "rpc-error"
        result = self.run_command("--force")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.home / "codex-import-receipt.json").exists())
        del self.environment["CODEX_IMPORT_TEST_MODE"]
        self.assert_full_then_fast()
        (self.home / "codex-import-receipt.json").write_text("invalid receipt")
        self.assert_full_then_fast()

    def test_unknown_layout_custom_database_and_unwritable_receipt_fall_back(self):
        self.receipt_fixture()
        self.assert_full_then_fast()
        newer = self.home / "state_6.sqlite"
        newer.touch()
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Session import complete.", result.stdout)
        self.assertIn("unsupported Codex state database layout", result.stderr)
        newer.unlink()
        self.assert_full_then_fast()
        config = self.home / "config.toml"
        config.write_text('sqlite_home = "/a/different/state/directory"\n')
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("custom sqlite_home", result.stderr)
        config.unlink()
        self.assert_full_then_fast()
        receipt = self.home / "codex-import-receipt.json"
        receipt.unlink()
        receipt.mkdir()
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Session import complete.", result.stdout)
        self.assertIn("warning: receipt unavailable", result.stderr)
        receipt.rmdir()
        self.assert_full_then_fast()

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
        # Current-session listing omits rollouts without user events; archived
        # listing includes them. Keep this receipt case in the current directory.
        ignored_id = str(uuid.uuid4())
        ignored = self.home / "sessions/2026/01/01" / f"rollout-2026-01-01T10-00-00-{ignored_id}.jsonl"
        ignored_events = json.loads(json.dumps(events[:2]))
        ignored_events[0]["payload"]["id"] = ignored_id
        ignored.write_text("".join(json.dumps(dict(event, timestamp=stamp)) + "\n" for event in ignored_events))
        originals[ignored] = ignored.read_bytes()
        for iteration in range(2):
            result = self.run_command()
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("Session import complete." if iteration == 0 else "Session index is current.", result.stdout)
            with sqlite3.connect(self.home / "state_5.sqlite") as db:
                self.assertEqual(set(ids), {row[0] for row in db.execute("SELECT id FROM threads")})
                self.assertEqual(marker, db.execute("SELECT * FROM backfill_state").fetchall())
            for path, original in originals.items():
                self.assertEqual(original, path.read_bytes())
        self.assertEqual([], list(self.home.glob("state_5.before-reimport.*")))
        forced = self.run_command("--force")
        self.assertEqual(0, forced.returncode, forced.stderr)
        self.assertIn("Session import complete.", forced.stdout)
        self.assertIsNone(active.poll())
        self.assertEqual(ids[0], rpc(3, "thread/read", {"threadId": ids[0]})["thread"]["id"])


if __name__ == "__main__":
    unittest.main()
