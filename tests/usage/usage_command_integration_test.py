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

    def test_usage_propagates_du_failure_without_sorting(self) -> None:
        marker = self.directory / "sort-called"
        self.executable("du", "exit 27\n")
        self.executable("sort", f"touch {marker}\n")

        result = subprocess.run(
            [str(ROOT / "bin/usage"), str(self.directory)],
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(27, result.returncode)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
