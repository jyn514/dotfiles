#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SetupIdempotenceTests(unittest.TestCase):
    def test_backup_option_does_not_duplicate_its_cron_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            home = directory / "home"
            binaries = directory / "bin"
            crontab_state = directory / "crontab"
            home.mkdir()
            binaries.mkdir()
            crontab = binaries / "crontab"
            crontab.write_text(
                "#!/bin/sh\n"
                'if [ "${1:-}" = -l ]; then\n'
                '  [ ! -e "$CRONTAB_STATE" ] || cat "$CRONTAB_STATE"\n'
                "else\n"
                '  cp "$1" "$CRONTAB_STATE"\n'
                "fi\n"
            )
            crontab.chmod(0o755)
            env = os.environ.copy()
            env.update(
                CRONTAB_STATE=str(crontab_state),
                HOME=str(home),
                PATH=f"{binaries}:{env['PATH']}",
            )

            results = [
                subprocess.run(
                    ["./setup", "5"],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                for _ in range(2)
            ]

            for result in results:
                self.assertEqual(0, result.returncode, result.stderr)
            entries = crontab_state.read_text().splitlines()
            self.assertEqual(1, len(entries))
            self.assertTrue(entries[0].endswith("/bin/backup"))

    def test_kde_keybinding_patch_accepts_an_already_applied_patch(self) -> None:
        setup = (ROOT / "setup").read_text()

        self.assertIn("patch --forward --silent", setup)
        self.assertIn("patch --reverse --dry-run --silent", setup)


if __name__ == "__main__":
    unittest.main()
