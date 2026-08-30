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

    def test_callgraph_comparison_stops_before_diff_on_read_failure(self) -> None:
        marker = self.directory / "diff-called"
        self.executable("diff", f"touch {marker}\n")

        result = subprocess.run(
            [str(ROOT / "bin/callgraph-cmp"), "missing.dot", "second.dot"],
            cwd=self.directory,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertFalse(marker.exists())
    def test_callgraph_comparison_accepts_graphs_without_edges(self) -> None:
        (self.directory / "first.dot").write_text("digraph {}\n")
        (self.directory / "second.dot").write_text("digraph {}\n")

        result = subprocess.run(
            [str(ROOT / "bin/callgraph-cmp"), "first.dot", "second.dot"],
            cwd=self.directory,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
