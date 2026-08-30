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

    def test_callgraph_stops_at_each_failed_producer(self) -> None:
        self.executable(
            "valgrind",
            '[ "${FAIL_STAGE:-}" = valgrind ] && exit 23\nprintf "valgrind\\n" >> "$CALLS"\n',
        )
        self.executable(
            "gprof2dot",
            '[ "${FAIL_STAGE:-}" = gprof2dot ] && exit 24\nprintf "gprof2dot\\n" >> "$CALLS"\nprintf "digraph {}\\n"\n',
        )
        self.executable(
            "dot",
            '[ "${FAIL_STAGE:-}" = dot ] && exit 25\nprintf "dot\\n" >> "$CALLS"\nprintf "png\\n"\n',
        )
        calls = self.directory / "calls"
        environment = os.environ | {
            "CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for stage, expected in (("valgrind", 23), ("gprof2dot", 24), ("dot", 25)):
            calls.unlink(missing_ok=True)
            result = subprocess.run(
                [str(ROOT / "bin/callgraph"), "program"],
                cwd=self.directory,
                env=environment | {"FAIL_STAGE": stage},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(expected, result.returncode, stage)
            self.assertNotIn("generated callgraph", result.stdout)


if __name__ == "__main__":
    unittest.main()
