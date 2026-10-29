import importlib.util
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
            cwd=self.directory,
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
                    "zope-interface",
                ],
            ],
            self.recorded_calls(),
        )
        self.assertIn(b"Packages to upgrade:\n  alpha\n  Zope.Interface\n", result.stderr)
        self.assertIn(b"Upgrade 2 packages? [y/N] ", result.stderr)

    def test_install_canonicalizes_and_deduplicates_without_changing_confirmation(self) -> None:
        self.pip()
        names = ["demo.tar.gz", "Demo_Tar_Gz", "demo-tar-gz"]

        result = self.run_command(
            "--index-url", "https://example.invalid/simple",
            reply=b"y\n",
            environment={"PIP_LIST": json.dumps([{"name": name} for name in names])},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["install", "-U", "--index-url", "https://example.invalid/simple", "demo-tar-gz"],
            self.recorded_calls()[1],
        )
        for name in names:
            self.assertIn(f"  {name}\n".encode(), result.stderr)
        self.assertIn(b"Upgrade 3 packages? [y/N] ", result.stderr)

    @unittest.skipUnless(
        importlib.util.find_spec("pip"), "native pip parser unavailable in test interpreter"
    )
    def test_native_parser_keeps_archive_names_in_requirement_namespace(self) -> None:
        self.pip()
        (self.directory / "demo.tar.gz").write_bytes(b"inert parser-only archive fixture")
        project = self.directory / "demo-tar-gz"
        project.mkdir()
        (project / "setup.py").write_text("raise AssertionError('must never execute')\n")
        (project / "pyproject.toml").write_text(
            '[build-system]\nrequires = []\nbuild-backend = "never_execute"\n'
        )
        result = self.run_command(
            "--yes", environment={"PIP_LIST": '[{"name":"demo.tar.gz"}]'}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        arguments = self.recorded_calls()[1][2:]
        probe = subprocess.run(
            [
                sys.executable, "-c",
                "import json, sys\n"
                "from pip._internal.req.constructors import install_req_from_line\n"
                "def parse(value):\n"
                "    req = install_req_from_line(value)\n"
                "    return {\n"
                "        'name': req.req.name if req.req is not None else None,\n"
                "        'link': str(req.link) if req.link is not None else None,\n"
                "        'specifier': str(req.specifier) if req.req is not None else None,\n"
                "        'prereleases': req.specifier.prereleases if req.req is not None else None,\n"
                "    }\n"
                "print(json.dumps([parse(value) for value in sys.argv[1:]]))\n",
                "demo.tar.gz", "./demo-tar-gz", *arguments,
            ],
            cwd=self.directory,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, probe.returncode, probe.stderr)
        archive, directory, *requirements = json.loads(probe.stdout)
        # Controls prove these exact fixtures are recognized as filesystem inputs.
        self.assertEqual((self.directory / "demo.tar.gz").as_uri(), archive["link"])
        self.assertIsNone(archive["name"])
        self.assertEqual(project.as_uri(), directory["link"])
        self.assertIsNone(directory["name"])
        self.assertEqual(
            [{"name": "demo-tar-gz", "link": None, "specifier": "", "prereleases": None}],
            requirements,
        )

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
                ["install", "-U", "--yes", "alpha", "zope-interface"],
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
