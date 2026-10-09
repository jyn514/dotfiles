#!/usr/bin/env python3
"""Protect the backup-before-reset contract for manual Codex session import."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/codex-import"


class CodexImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "codex home's state"
        self.home.mkdir()
        self.fake_bin = Path(self.temporary.name) / "bin"
        self.fake_bin.mkdir()
        (self.fake_bin / "codex").symlink_to(
            Path(__file__).parent / "fixtures/codex-import-cli"
        )
        self.database = self.home / "state_5.sqlite"
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE backfill_state "
            "(id INTEGER PRIMARY KEY, status TEXT, last_watermark TEXT, updated_at INTEGER)"
        )
        self.connection.execute(
            "INSERT INTO backfill_state VALUES (1, 'complete', 'sessions/newest', 123)"
        )
        self.connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
        self.connection.execute("INSERT INTO threads VALUES ('keep-this-thread')")
        self.connection.commit()
        self.environment = dict(
            os.environ, CODEX_HOME=str(self.home),
            PATH=f"{self.fake_bin}:{os.environ['PATH']}",
        )

    def run_command(self):
        return subprocess.run(
            [str(COMMAND)], env=self.environment, capture_output=True, text=True,
        )

    def marker(self, connection):
        return connection.execute("SELECT * FROM backfill_state").fetchone()

    def test_backup_includes_wal_and_reset_keeps_threads_on_repeated_runs(self):
        locks = self.home / "thread-writer-locks"
        locks.mkdir()
        (locks / "closed-session.lock").touch()
        for expected_backups in (1, 2):
            result = self.run_command()
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual((1, "complete", None, 0), self.marker(self.connection))
            self.assertEqual(
                [("keep-this-thread",)],
                self.connection.execute("SELECT * FROM threads").fetchall(),
            )
            backups = sorted(self.home.glob("state_5.before-reimport.*"))
            self.assertEqual(expected_backups, len(backups))
            self.assertIn("Session import complete", result.stdout)
            self.assertIn("Backing up", result.stderr)
        markers = []
        for backup in backups:
            with sqlite3.connect(backup) as saved:
                markers.append(self.marker(saved))
                self.assertEqual(
                    [("keep-this-thread",)], saved.execute("SELECT * FROM threads").fetchall(),
                )
        self.assertIn((1, "complete", "sessions/newest", 123), markers)

    def test_failed_daemon_stop_leaves_database_unchanged_without_backup(self):
        (self.fake_bin / "codex").unlink()
        (self.fake_bin / "codex").symlink_to(shutil.which("false"))
        result = self.run_command()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual((1, "complete", "sessions/newest", 123), self.marker(self.connection))
        self.assertEqual([], list(self.home.glob("state_5.before-reimport.*")))
        self.assertNotIn("Session import complete", result.stdout)

    def test_failed_backup_leaves_database_unchanged(self):
        (self.fake_bin / "sqlite3").symlink_to(shutil.which("false"))
        result = self.run_command()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual((1, "complete", "sessions/newest", 123), self.marker(self.connection))
        self.assertNotIn("Session import complete", result.stdout)

    def test_import_through_wrapper_is_accepted_by_installed_codex(self):
        # An argument-printing mock cannot catch CLI/profile incompatibilities.
        real_path = os.pathsep.join(
            entry for entry in os.environ["PATH"].split(os.pathsep)
            if Path(entry).resolve() != (ROOT / "bin").resolve()
        )
        real_codex = shutil.which("codex", path=real_path)
        if real_codex is None:
            self.skipTest("Codex CLI is not installed")
        (self.fake_bin / "codex").unlink()
        (self.fake_bin / "codex").symlink_to(Path(real_codex).resolve())
        (self.home / "developer-instructions.md").write_text("")
        self.environment["DOTFILES_SANDBOX"] = "1"
        self.environment["PATH"] = f"{ROOT / 'bin'}:{self.environment['PATH']}"
        # Use Codex's real schema, then simulate a rollout arriving through sync.
        self.connection.close()
        self.database.unlink()
        initialized = subprocess.run(
            [real_codex, "app-server", "--stdio"], env=self.environment,
            stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        thread_id = str(uuid.uuid4())
        sessions = self.home / "sessions/2026/10/09"
        sessions.mkdir(parents=True)
        rollout = sessions / f"rollout-2026-10-09T10-00-00-{thread_id}.jsonl"
        rollout.write_text(json.dumps({
            "timestamp": "2026-10-09T10:00:00Z", "type": "session_meta",
            "payload": {
                "id": thread_id, "timestamp": "2026-10-09T10:00:00Z",
                "cwd": str(self.home), "originator": "codex_cli_rs",
                "cli_version": "0.159.2", "source": "cli", "model_provider": "openai",
            },
        }) + "\n")
        contents = rollout.read_bytes()
        result = self.run_command()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ("complete",), self.connection.execute("SELECT status FROM backfill_state").fetchone(),
        )
        self.assertEqual(
            [(thread_id,)], self.connection.execute("SELECT id FROM threads").fetchall(),
        )
        self.assertEqual(contents, rollout.read_bytes())
        self.assertEqual([rollout], list(self.home.glob("sessions/**/*.jsonl")))
        self.assertIn("Session import complete", result.stdout)
        backups = list(self.home.glob("state_5.before-reimport.*"))
        self.assertEqual(1, len(backups))
        with sqlite3.connect(backups[0]) as saved:
            self.assertEqual((0,), saved.execute("SELECT count(*) FROM threads").fetchone())

    def test_failed_or_incomplete_import_keeps_backup_and_allows_retry(self):
        for outcome in ("fail", "incomplete"):
            with self.subTest(outcome=outcome):
                self.environment["CODEX_IMPORT_TEST_STARTUP"] = outcome
                result = self.run_command()
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("Session import complete", result.stdout)
                self.assertIn("retry codex-import", result.stderr)
                self.assertEqual((1, "pending", None, 0), self.marker(self.connection))
                self.assertTrue(list(self.home.glob("state_5.before-reimport.*")))
                del self.environment["CODEX_IMPORT_TEST_STARTUP"]
                self.assertEqual(0, self.run_command().returncode)
                self.assertEqual((1, "complete", None, 0), self.marker(self.connection))

    def test_running_session_refuses_before_daemon_stop_or_backup(self):
        locks = self.home / "thread-writer-locks"
        locks.mkdir()
        with (locks / "running-session.lock").open("wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_command()
        self.assertEqual(1, result.returncode)
        self.assertIn("local sessions are running: running-session", result.stderr)
        self.assertIn("left unchanged", result.stderr)
        self.assertNotIn("Stopping Codex daemon", result.stderr)
        self.assertEqual((1, "complete", "sessions/newest", 123), self.marker(self.connection))
        self.assertEqual([], list(self.home.glob("state_5.before-reimport.*")))
        self.assertEqual(0, self.run_command().returncode)

    def test_unreadable_lock_directory_refuses_before_daemon_stop(self):
        (self.home / "thread-writer-locks").write_text("invalid lock directory")
        result = self.run_command()
        self.assertEqual(1, result.returncode)
        self.assertIn("cannot check running sessions", result.stderr)
        self.assertNotIn("Stopping Codex daemon", result.stderr)
        self.assertEqual((1, "complete", "sessions/newest", 123), self.marker(self.connection))
        self.assertEqual([], list(self.home.glob("state_5.before-reimport.*")))


if __name__ == "__main__":
    unittest.main()
