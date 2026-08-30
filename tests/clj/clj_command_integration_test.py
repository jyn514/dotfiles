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


ROOT = Path(__file__).resolve().parents[2]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_clj_ignores_ambient_args_and_propagates_alias_query_failure(self) -> None:
        calls = self.directory / "clojure-calls"
        self.executable(
            "clojure",
            'if [ "$1 $2" = "-X:deps aliases" ]; then\n'
            '  [ -z "${QUERY_STATUS:-}" ] || exit "$QUERY_STATUS"\n'
            '  printf "%s\\n" "${ALIASES:-}"\n'
            'else\n'
            '  printf "<%s>\\n" "$@" > "$CLOJURE_CALLS"\n'
            'fi\n',
        )
        environment = os.environ | {
            "args": "ambient injected arguments",
            "CLOJURE_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        ordinary = subprocess.run(
            [str(ROOT / "bin/clj"), "user-argument"], env=environment, check=False
        )
        ordinary_calls = calls.read_text()
        calls.unlink()
        development = subprocess.run(
            [str(ROOT / "bin/clj")],
            env=environment | {"ALIASES": ":dev"},
            check=False,
        )
        development_calls = calls.read_text()
        calls.unlink()
        failed = subprocess.run(
            [str(ROOT / "bin/clj")],
            env=environment | {"QUERY_STATUS": "23"},
            check=False,
        )

        self.assertEqual(0, ordinary.returncode)
        self.assertNotIn("ambient", ordinary_calls)
        self.assertIn("<user-argument>", ordinary_calls)
        self.assertEqual(0, development.returncode)
        self.assertIn("<-A:dev>", development_calls)
        self.assertEqual(23, failed.returncode)
        self.assertFalse(calls.exists())


if __name__ == "__main__":
    unittest.main()
