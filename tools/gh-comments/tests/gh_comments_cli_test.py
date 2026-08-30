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

    def test_gh_comments_normalizes_url_and_rejects_unsafe_issue_names(self) -> None:
        calls = self.directory / "gh-calls"
        self.executable(
            "gh",
            'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
            'case " $* " in *" --json "*) printf \'{}\\n\';; '
            "*) printf 'issue output\\n';; esac\n",
        )
        self.executable("less", 'exit "${LESS_STATUS:-0}"\n')
        environment = os.environ | {
            "GH_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "github.com/user/repo/issues/123"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        unsafe = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "user/repo", "../escape"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("https://github.com/user/repo/issues/123", calls.read_text())
        self.assertEqual(2, len(calls.read_text().splitlines()))
        self.assertEqual(1, unsafe.returncode)
        self.assertFalse((self.directory.parent / "escape.json").exists())
    def test_gh_comments_does_not_publish_partial_exports(self) -> None:
        self.executable(
            "gh",
            'case " $* " in\n'
            '  *" --json "*) printf "json\\n"; '
            '[ -z "${GH_STATUS:-}" ] || exit "$GH_STATUS";;\n'
            '  *) printf "text\\n"; '
            '[ -z "${TEXT_STATUS:-}" ] || exit "$TEXT_STATUS";;\n'
            "esac\n",
        )
        self.executable("less", 'exit "${LESS_STATUS:-0}"\n')
        environment = os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"}

        for variable, status in (("GH_STATUS", 24), ("TEXT_STATUS", 25)):
            result = subprocess.run(
                [str(ROOT / "bin/gh-comments"), "user/repo", "123"],
                cwd=self.directory,
                env=environment | {variable: str(status)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(status, result.returncode, variable)
            self.assertFalse((self.directory / "123.json").exists())
            self.assertFalse((self.directory / "123.txt").exists())
            self.assertEqual([], list(self.directory.glob(".123.*")))

        less_failure = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "user/repo", "123"],
            cwd=self.directory,
            env=environment | {"LESS_STATUS": "26"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(26, less_failure.returncode)
        self.assertEqual("json\n", (self.directory / "123.json").read_text())
        self.assertEqual("text\n", (self.directory / "123.txt").read_text())


if __name__ == "__main__":
    unittest.main()
