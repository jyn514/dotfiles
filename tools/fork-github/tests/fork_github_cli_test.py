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

    def test_fork_github_strips_page_url_suffixes(self) -> None:
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'if [ "$1" = clone ]; then mkdir "$4"; fi\n',
        )

        result = subprocess.run(
            [
                str(ROOT / "bin/fork-github"),
                "https://github.com/user/repository?tab=readme-ov-file",
            ],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "GIT_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "clone --filter=blob:none https://github.com/user/repository.git repository",
            calls.read_text().splitlines()[0],
        )
    def test_fork_github_keeps_repository_name_when_checkout_directory_differs(self) -> None:
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "<%s>\\n" "$@" >> "$GIT_CALLS"\n'
            'if [ "$1" = clone ]; then mkdir "$4"; fi\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/fork-github"), "owner/repository", "custom checkout"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        missing = subprocess.run(
            [str(ROOT / "bin/fork-github")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("custom checkout\n", result.stdout)
        self.assertEqual(
            ["<remote>", "<add>", "<origin>", "<git@github.com:jyn514/repository.git>"],
            calls.read_text().splitlines()[-4:],
        )
        self.assertEqual(2, missing.returncode)
        self.assertIn("usage:", missing.stderr)


if __name__ == "__main__":
    unittest.main()
