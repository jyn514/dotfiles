import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
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

    def test_remote_git_url_handles_spaces_and_blank_lines_offline(self) -> None:
        repository = self.directory / "repository with spaces"
        repository.mkdir()
        source = repository / "file #%? with spaces"
        source.write_text("unique line\n\n")
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'case "$1 $2" in\n'
            '  "rev-parse --show-toplevel") printf "%s\\n" "$REPOSITORY";;\n'
            '  "remote get-url") printf "https://github.com/user/repo.git\\n";;\n'
            '  "remote ") printf "origin\\n";;\n'
            '  "rev-list --remotes") printf "abc123\\n";;\n'
            '  "ls-tree -r") printf "%s\\0" "$RELATIVE";;\n'
            '  "show "*) printf "unique line\\n\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "RELATIVE": source.name,
            "REPOSITORY": str(repository.resolve()),
        }

        matched = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        blank = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "2"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(1, matched.returncode, matched.stderr)
        self.assertEqual(
            "https://github.com/user/repo/blob/abc123/file%20%23%25%3F%20with%20spaces#L1\n",
            matched.stdout,
            matched.stderr + calls.read_text(),
        )
        self.assertEqual(1, blank.returncode)
        self.assertEqual(
            "https://github.com/user/repo/blob/HEAD/file%20%23%25%3F%20with%20spaces#L2\n",
            blank.stdout,
        )
        call_lines = calls.read_text().splitlines()
        self.assertNotIn("remote set-head --auto origin", call_lines)
        self.assertEqual(1, sum(line.startswith("show abc123:") for line in call_lines))
    def test_remote_git_url_propagates_git_failures_and_rejects_unknown_hosts(self) -> None:
        repository = self.directory / "repository"
        repository.mkdir()
        source = repository / "file"
        source.write_text("unique line\n")
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "rev-parse --show-toplevel") printf "%s\\n" "$REPOSITORY";;\n'
            '  "remote get-url") printf "%s\\n" "$REMOTE_URL";;\n'
            '  "remote ") printf "origin\\n";;\n'
            '  "rev-list --remotes") [ "${REV_LIST_STATUS:-0}" -eq 0 ] || exit "$REV_LIST_STATUS"; printf "abc123\\n";;\n'
            '  "ls-tree -r") printf "%s\\0" "$RELATIVE";;\n'
            '  "show "*) exit "${SHOW_STATUS:-0}";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "RELATIVE": source.name,
            "REPOSITORY": str(repository.resolve()),
            "REMOTE_URL": "https://github.com/user/repo.git",
            "REV_LIST_STATUS": "23",
        }

        failed_query = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        failed_grep = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"REV_LIST_STATUS": "0", "SHOW_STATUS": "24"},
        )
        unsupported = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment
            | {
                "REMOTE_URL": "https://codeberg.org/user/repo.git",
                "REV_LIST_STATUS": "0",
            },
        )

        self.assertEqual(23, failed_query.returncode)
        self.assertEqual("", failed_query.stdout)
        self.assertEqual(24, failed_grep.returncode)
        self.assertEqual("", failed_grep.stdout)
        self.assertEqual(2, unsupported.returncode)
        self.assertEqual("", unsupported.stdout)
        self.assertIn("unsupported upstream", unsupported.stderr)
    def test_remote_git_url_validates_ranges_before_running_git(self) -> None:
        source = self.directory / "file"
        source.write_text("one\ntwo\n")
        calls = self.directory / "git-calls"
        self.executable("git", 'touch "$GIT_CALLS"\nexit 99\n')
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for lines in (("expression",), ("0",), ("00",), ("2", "1")):
            result = subprocess.run(
                [str(ROOT / "bin/remote-git-url"), str(source), *lines],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(2, result.returncode, lines)
        self.assertFalse(calls.exists())
    def test_remote_git_url_propagates_remote_and_source_read_failures(self) -> None:
        repository = self.directory / "repository"
        repository.mkdir()
        source = repository / "file"
        source.write_text("line\n")
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "rev-parse --show-toplevel") printf "%s\\n" "$REPOSITORY";;\n'
            '  "remote ") status=${REMOTE_STATUS:-23}; [ "$status" -eq 0 ] || exit "$status"; printf "origin\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "REPOSITORY": str(repository.resolve()),
        }

        remote_failure = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        source.unlink()
        read_failure = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            env=environment | {"REMOTE_STATUS": "0"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(23, remote_failure.returncode)
        self.assertEqual(1, read_failure.returncode)
        self.assertIn("could not read", read_failure.stderr)


if __name__ == "__main__":
    unittest.main()
