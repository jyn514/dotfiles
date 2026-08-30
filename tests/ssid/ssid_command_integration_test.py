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

    def test_ssid_preserves_spaces_from_machine_readable_output(self) -> None:
        calls = self.directory / "nmcli-calls"
        self.executable(
            "nmcli",
            'printf "%s\\n" "$*" > "$NMCLI_CALLS"\n'
            "printf 'no:Other Network\\nyes:Justice:of\\\\Toren\\n'\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/ssid")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "NMCLI_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("Justice:of\\Toren\n", result.stdout)
        self.assertEqual(
            "--terse --escape no --fields active,ssid device wifi\n",
            calls.read_text(),
        )
    def test_ssid_propagates_nmcli_failure(self) -> None:
        self.executable("nmcli", "exit 27\n")

        result = subprocess.run(
            [str(ROOT / "bin/ssid")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(27, result.returncode)
        self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
