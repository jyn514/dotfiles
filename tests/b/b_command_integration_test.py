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

    def test_b_enters_workspace_and_preserves_metadata_failures(self) -> None:
        workspace = self.directory / "workspace with spaces"
        workspace.mkdir()
        bacon_cwd = self.directory / "bacon-cwd"
        self.executable(
            "cargo",
            'if [ -n "${CARGO_STATUS:-}" ]; then exit "$CARGO_STATUS"; fi\n'
            'if [ -n "${MALFORMED_METADATA:-}" ]; then printf "not json\\n"; '
            'else printf \'{"workspace_root":"%s"}\\n\' "$WORKSPACE"; fi\n',
        )
        self.executable("bacon", 'pwd > "$BACON_CWD"\n')
        environment = os.environ | {
            "BACON_CWD": str(bacon_cwd),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "WORKSPACE": str(workspace),
        }

        success = subprocess.run([str(ROOT / "bin/b")], env=environment, check=False)
        cargo_failure = subprocess.run(
            [str(ROOT / "bin/b")], env=environment | {"CARGO_STATUS": "23"}, check=False
        )
        malformed = subprocess.run(
            [str(ROOT / "bin/b")],
            env=environment | {"MALFORMED_METADATA": "1"},
            check=False,
        )

        self.assertEqual(0, success.returncode)
        self.assertEqual(f"{workspace.resolve()}\n", bacon_cwd.read_text())
        self.assertEqual(23, cargo_failure.returncode)
        self.assertEqual(1, malformed.returncode)


if __name__ == "__main__":
    unittest.main()
