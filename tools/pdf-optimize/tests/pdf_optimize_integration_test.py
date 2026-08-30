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

    def test_pdf_optimize_propagates_ghostscript_failure(self) -> None:
        source = self.directory / "source.pdf"
        output = self.directory / "output.pdf"
        source.write_text("pdf\n")
        self.executable("file", "printf 'PDF document\\n'\n")
        self.executable("gs", "exit 42\n")

        result = subprocess.run(
            [str(ROOT / "bin/pdf-optimize"), str(source), str(output)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertEqual(42, result.returncode)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
