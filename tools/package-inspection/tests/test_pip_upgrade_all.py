import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/pip-upgrade-all"


class PipUpgradeAllTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.calls = self.directory / "calls"

    def pip(self) -> None:
        path = self.directory / "pip"
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open(os.environ['PIP_CALLS'], 'a') as stream:\n"
            "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1] == 'list':\n"
            "    sys.stdout.write(os.environ.get('PIP_LIST', '[]'))\n"
            "    sys.stderr.write(os.environ.get('PIP_LIST_STDERR', ''))\n"
            "    raise SystemExit(int(os.environ.get('PIP_LIST_STATUS', '0')))\n"
            "raise SystemExit(int(os.environ.get('PIP_INSTALL_STATUS', '0')))\n"
        )
        path.chmod(0o755)

    def run_command(
        self, *arguments: str, reply: bytes = b"", environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        values = {
            "PATH": str(self.directory),
            "PIP_CALLS": str(self.calls),
            "PIP_LIST": '[{"name":"Zope.Interface"},{"name":"alpha"}]',
        }
        if environment:
            values.update(environment)
        return subprocess.run(
            [sys.executable, str(COMMAND), *arguments],
            input=reply,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=values,
            check=False,
        )

    def recorded_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_confirmation_precedes_exact_upgrade_command(self) -> None:
        self.pip()

        result = self.run_command("--index-url", "https://example.invalid/simple", reply=b"y\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                ["list", "--format=json"],
                [
                    "install",
                    "-U",
                    "--index-url",
                    "https://example.invalid/simple",
                    "alpha",
                    "Zope.Interface",
                ],
            ],
            self.recorded_calls(),
        )
        self.assertIn(b"Packages to upgrade:\n  alpha\n  Zope.Interface\n", result.stderr)
        self.assertIn(b"Upgrade 2 packages? [y/N] ", result.stderr)

    def test_rejection_and_end_of_input_do_not_mutate(self) -> None:
        self.pip()
        rejected = self.run_command(reply=b"n\n")
        self.assertEqual(0, rejected.returncode, rejected.stderr)
        self.assertEqual([["list", "--format=json"]], self.recorded_calls())

        self.calls.unlink()
        ended = self.run_command()
        self.assertEqual(0, ended.returncode, ended.stderr)
        self.assertEqual([["list", "--format=json"]], self.recorded_calls())

    def test_yes_option_is_owned_and_double_dash_forwards_later_value(self) -> None:
        self.pip()

        result = self.run_command("--yes", "--", "--yes")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                ["list", "--format=json"],
                ["install", "-U", "--yes", "alpha", "Zope.Interface"],
            ],
            self.recorded_calls(),
        )
        self.assertNotIn(b"[y/N]", result.stderr)

    def test_empty_or_malformed_listing_never_mutates(self) -> None:
        self.pip()
        empty = self.run_command(environment={"PIP_LIST": "[]"})
        self.assertEqual(0, empty.returncode, empty.stderr)
        self.assertEqual([["list", "--format=json"]], self.recorded_calls())

        self.calls.unlink()
        malformed = self.run_command(environment={"PIP_LIST": '{"name":"not-a-list"}'})
        self.assertEqual(1, malformed.returncode)
        self.assertIn(b"malformed package data", malformed.stderr)
        self.assertEqual([["list", "--format=json"]], self.recorded_calls())

    def test_listing_and_install_failures_propagate_exactly(self) -> None:
        self.pip()
        listing = self.run_command(
            "--yes",
            environment={
                "PIP_LIST": '[{"name":"partial"}',
                "PIP_LIST_STDERR": "list failed\n",
                "PIP_LIST_STATUS": "24",
            },
        )
        self.assertEqual(24, listing.returncode)
        self.assertEqual(b"", listing.stdout)
        self.assertEqual(b"list failed\n", listing.stderr)
        self.assertEqual([["list", "--format=json"]], self.recorded_calls())

        self.calls.unlink()
        install = self.run_command("--yes", environment={"PIP_INSTALL_STATUS": "25"})
        self.assertEqual(25, install.returncode)
        self.assertEqual(2, len(self.recorded_calls()))

    def test_missing_pip_is_reported(self) -> None:
        result = self.run_command()

        self.assertEqual(127, result.returncode)
        self.assertEqual(b"pip not found\n", result.stderr)


if __name__ == "__main__":
    unittest.main()
