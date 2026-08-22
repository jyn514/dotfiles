#!/usr/bin/env python3

import os
import shlex
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestRunnerTests(unittest.TestCase):
    def test_pytest_plugin_options_match_the_lock(self) -> None:
        config = tomllib.loads((ROOT / "config/mise.toml").read_text())
        lock = tomllib.loads((ROOT / "config/mise.lock").read_text())

        configured = shlex.split(config["tools"]["pipx:pytest"]["uvx_args"])
        locked = shlex.split(
            lock["tools"]["pipx:pytest"][0]["options"]["uvx_args"]
        )
        self.assertEqual(configured, locked)

    def test_jobs_are_dispatched_to_pytest_and_failures_are_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev").mkdir()
            (root / "dev/test").write_bytes((ROOT / "dev/test").read_bytes())
            (root / "dev/test").chmod(0o755)
            bin_directory = root / "bin"
            bin_directory.mkdir()
            log = root / "pytest.args"
            pytest = bin_directory / "pytest"
            pytest.write_text(
                "#!/bin/sh\n"
                "if [ \"${1-}\" = --help ]; then\n"
                "  echo '--instafail --numprocesses --force-sugar'\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' \"$@\" > \"$TEST_LOG\"\n"
                "exit 23\n"
            )
            pytest.chmod(0o755)
            environment = os.environ | {
                "PATH": f"{bin_directory}:{os.environ['PATH']}",
                "TEST_LOG": str(log),
            }

            result = subprocess.run(
                [root / "dev/test", "--jobs", "3"],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
            )

            self.assertEqual(23, result.returncode)
            arguments = log.read_text().splitlines()
            self.assertEqual("3", arguments[arguments.index("-n") + 1])
            self.assertIn("--instafail", arguments)

    def test_rejects_invalid_job_counts_before_dispatch(self) -> None:
        result = subprocess.run(
            [ROOT / "dev/test", "--jobs", "0"], text=True, capture_output=True
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("positive integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
