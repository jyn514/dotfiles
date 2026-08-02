import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMMAND = ROOT / "bin/purge-removed"


class PurgeRemovedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.query_calls = self.directory / "query-calls"
        self.sudo_calls = self.directory / "sudo-calls"

    def program(self, name: str, source: str) -> Path:
        path = self.directory / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)
        return path

    def query(self) -> None:
        self.program(
            "dpkg-query",
            "import json, os, sys\n"
            "open(os.environ['QUERY_CALLS'], 'w').write(json.dumps(sys.argv[1:]))\n"
            "sys.stdout.buffer.write(os.environ.get('QUERY_OUTPUT', '').encode())\n"
            "sys.stderr.write(os.environ.get('QUERY_STDERR', ''))\n"
            "raise SystemExit(int(os.environ.get('QUERY_STATUS', '0')))\n",
        )

    def mutation_tools(self) -> Path:
        dpkg = self.program("dpkg", "raise SystemExit(99)\n")
        self.program(
            "sudo",
            "import json, os, sys\n"
            "open(os.environ['SUDO_CALLS'], 'w').write(json.dumps(sys.argv[1:]))\n"
            "raise SystemExit(int(os.environ.get('SUDO_STATUS', '0')))\n",
        )
        return dpkg

    def run_command(
        self, *arguments: str, reply: bytes = b"", environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        values = {
            "PATH": str(self.directory),
            "QUERY_CALLS": str(self.query_calls),
            "SUDO_CALLS": str(self.sudo_calls),
            "QUERY_OUTPUT": "ii \tinstalled\nrc \tzeta\nrc \talpha:amd64\n",
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

    def test_confirmation_precedes_exact_sudo_command(self) -> None:
        self.query()
        dpkg = self.mutation_tools()

        result = self.run_command(reply=b"y\n")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["-W", "-f=${db:Status-Abbrev}\t${binary:Package}\n"],
            json.loads(self.query_calls.read_text()),
        )
        self.assertEqual(
            [str(dpkg), "--purge", "--", "alpha:amd64", "zeta"],
            json.loads(self.sudo_calls.read_text()),
        )
        self.assertIn(b"Residual-config packages to purge:\n  alpha:amd64\n  zeta\n", result.stderr)
        self.assertIn(b"Purge 2 packages? [y/N] ", result.stderr)

    def test_rejection_and_end_of_input_do_not_mutate(self) -> None:
        self.query()
        self.mutation_tools()
        rejected = self.run_command(reply=b"n\n")
        self.assertEqual(0, rejected.returncode, rejected.stderr)
        self.assertFalse(self.sudo_calls.exists())
        ended = self.run_command()
        self.assertEqual(0, ended.returncode, ended.stderr)
        self.assertFalse(self.sudo_calls.exists())

    def test_yes_skips_prompt_and_propagates_sudo_failure(self) -> None:
        self.query()
        self.mutation_tools()

        result = self.run_command("--yes", environment={"SUDO_STATUS": "29"})

        self.assertEqual(29, result.returncode)
        self.assertNotIn(b"[y/N]", result.stderr)
        self.assertTrue(self.sudo_calls.exists())

    def test_empty_result_needs_no_mutation_tools(self) -> None:
        self.query()

        result = self.run_command(environment={"QUERY_OUTPUT": "ii \tinstalled\n"})

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(self.sudo_calls.exists())

    def test_failed_or_malformed_query_never_mutates(self) -> None:
        self.query()
        self.mutation_tools()
        failed = self.run_command(
            "--yes",
            environment={
                "QUERY_OUTPUT": "rc \tpartial\n",
                "QUERY_STDERR": "query failed\n",
                "QUERY_STATUS": "27",
            },
        )
        self.assertEqual(27, failed.returncode)
        self.assertEqual(b"query failed\n", failed.stderr)
        self.assertFalse(self.sudo_calls.exists())

        malformed = self.run_command("--yes", environment={"QUERY_OUTPUT": "rc malformed\n"})
        self.assertEqual(1, malformed.returncode)
        self.assertIn(b"malformed package data", malformed.stderr)
        self.assertFalse(self.sudo_calls.exists())

    def test_missing_commands_and_unknown_arguments_are_reported(self) -> None:
        missing_query = self.run_command()
        self.assertEqual(127, missing_query.returncode)
        self.assertEqual(b"dpkg-query not found\n", missing_query.stderr)

        self.query()
        missing_sudo = self.run_command("--yes")
        self.assertEqual(127, missing_sudo.returncode)
        self.assertEqual(b"sudo not found\n", missing_sudo.stderr.splitlines()[-1] + b"\n")

        invalid = self.run_command("--force")
        self.assertEqual(2, invalid.returncode)
        self.assertEqual(b"usage: purge-removed [--yes]\n", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
