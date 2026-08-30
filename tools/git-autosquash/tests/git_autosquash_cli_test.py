import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_git_autosquash_propagates_fallback_branch_failure(self) -> None:
        self.executable(
            "git",
            'case "$1" in\n'
            "  symbolic-ref) exit 1;;\n"
            "  for-each-ref) exit 24;;\n"
            "  *) exit 99;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/git-autosquash")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(24, result.returncode)
    def test_git_autosquash_only_defaults_remote_for_a_missing_config_key(self) -> None:
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'case "$1" in\n'
            '  symbolic-ref) printf "main\\n";;\n'
            '  config) exit "${CONFIG_STATUS:-1}";;\n'
            '  merge-base) printf "abc123\\n";;\n'
            '  revise) exit 0;;\n'
            'esac\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        missing = subprocess.run(
            [str(ROOT / "bin/git-autosquash")], env=environment, check=False
        )
        fatal = subprocess.run(
            [str(ROOT / "bin/git-autosquash")],
            env=environment | {"CONFIG_STATUS": "25"},
            check=False,
        )

        self.assertEqual(0, missing.returncode)
        self.assertIn("merge-base HEAD origin/HEAD", calls.read_text().splitlines())
        self.assertEqual(25, fatal.returncode)


if __name__ == "__main__":
    unittest.main()
