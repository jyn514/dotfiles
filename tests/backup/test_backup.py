#!/usr/bin/env python3

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.documents = self.directory / "Documents"
        self.documents.mkdir()
        self.log = self.directory / "calls"
        self.env_file = self.directory / "restic.env"
        self.env_file.write_text("export RESTIC_PASSWORD=test\n")
        restic = self.bin / "restic"
        restic.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$BACKUP_TEST_LOG"\n'
            'exit "${RESTIC_TEST_STATUS:-0}"\n'
        )
        restic.chmod(0o755)

    def run_backup(self, *arguments: str, status: int = 0) -> subprocess.CompletedProcess[str]:
        environment = os.environ | {
            "BACKUP_DOCUMENTS": str(self.documents),
            "BACKUP_HOME": str(self.directory),
            "BACKUP_TEST_LOG": str(self.log),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "RESTIC_CACHE_DIR": str(self.directory / "cache"),
            "RESTIC_ENV_FILE": str(self.env_file),
            "RESTIC_HOME": str(self.directory),
            "RESTIC_TEST_STATUS": str(status),
        }
        return subprocess.run(
            [str(ROOT / "bin/backup"), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_default_command_backs_up_one_documents_root(self) -> None:
        result = self.run_backup("--dry-run")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"backup --exclude notes/ --skip-if-unchanged "
            f"--cache-dir {self.directory}/cache --tag documents-backup --dry-run .\n",
            self.log.read_text(),
        )

    def test_check_reads_a_random_subset_without_the_persistent_cache(self) -> None:
        result = self.run_backup("check", "--no-lock")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "check --read-data-subset=5% --no-lock\n",
            self.log.read_text(),
        )

    def test_prune_has_an_explicit_retention_policy(self) -> None:
        result = self.run_backup("prune", "--dry-run")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"forget --cache-dir {self.directory}/cache --tag documents-backup "
            "--keep-daily 7 --keep-weekly 5 --keep-monthly 12 --keep-yearly 3 "
            "--prune --dry-run\ncheck\n",
            self.log.read_text(),
        )

    def test_failure_is_reported_and_preserved(self) -> None:
        result = self.run_backup("check", status=17)

        self.assertEqual(17, result.returncode)
        self.assertIn("backup: check failed with status 17", result.stderr)

    def test_unknown_command_does_not_invoke_restic(self) -> None:
        result = self.run_backup("destroy")

        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)
        self.assertFalse(self.log.exists())


@unittest.skipUnless(
    shutil.which("restic"),
    "restic is not installed; disposable repository integration unavailable",
)
class BackupResticIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.documents = self.directory / "Documents"
        (self.documents / "backups").mkdir(parents=True)
        (self.documents / "notes").mkdir()
        (self.documents / "backups" / "nested.txt").write_text("backup data\n")
        (self.documents / "letter.txt").write_text("document data\n")
        (self.documents / "notes" / "private.txt").write_text("excluded\n")
        self.repository = self.directory / "repository"
        self.cache = self.directory / "cache"
        self.env_file = self.directory / "restic.env"
        self.env_file.write_text(
            f"export RESTIC_REPOSITORY={self.repository}\n"
            "export RESTIC_PASSWORD=test-password\n"
        )
        self.environment = os.environ | {
            "BACKUP_DOCUMENTS": str(self.documents),
            "BACKUP_HOME": str(self.directory),
            "BACKUP_TAG": "integration-documents",
            "RESTIC_CACHE_DIR": str(self.cache),
            "RESTIC_ENV_FILE": str(self.env_file),
            "RESTIC_HOME": str(self.directory),
            "RESTIC_PASSWORD": "test-password",
            "RESTIC_REPOSITORY": str(self.repository),
        }
        self.run_restic("init")

    def run_restic(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["restic", *arguments],
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )

    def test_snapshot_has_one_root_and_restores_canonical_layout(self) -> None:
        backup = subprocess.run(
            [str(ROOT / "bin/backup")],
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, backup.returncode, backup.stderr)

        snapshots = json.loads(
            self.run_restic("snapshots", "--tag", "integration-documents", "--json").stdout
        )
        self.assertEqual(1, len(snapshots))
        self.assertEqual([str(self.documents)], snapshots[0]["paths"])

        listing = [
            json.loads(line)
            for line in self.run_restic(
                "ls", "latest", "--tag", "integration-documents", "--json"
            ).stdout.splitlines()
        ]
        paths = [entry["path"] for entry in listing if entry.get("struct_type") == "node"]
        self.assertEqual(1, paths.count("/backups/nested.txt"))
        self.assertNotIn("/notes/private.txt", paths)

        restore = self.directory / "restore"
        self.run_restic(
            "restore",
            "latest",
            "--tag",
            "integration-documents",
            "--target",
            str(restore),
        )
        self.assertEqual(
            "backup data\n",
            (restore / "backups" / "nested.txt").read_text(),
        )
        self.assertEqual("document data\n", (restore / "letter.txt").read_text())
        self.assertFalse((restore / "notes").exists())


if __name__ == "__main__":
    unittest.main()
