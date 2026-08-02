#!/usr/bin/env python3

import os
from pathlib import Path
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

    def test_default_command_preserves_backup_arguments(self) -> None:
        result = self.run_backup("--dry-run")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"backup {self.documents}/backups --exclude notes/ --skip-if-unchanged "
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


if __name__ == "__main__":
    unittest.main()
