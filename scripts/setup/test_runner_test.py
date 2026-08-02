#!/usr/bin/env python3

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestRunnerTests(unittest.TestCase):
    def test_pytest_plugins_are_locked_with_mise(self) -> None:
        config = tomllib.loads((ROOT / "config/mise.toml").read_text())
        lock = tomllib.loads((ROOT / "config/mise.lock").read_text())
        expected = "--with pytest-xdist --with pytest-sugar --with pytest-instafail"

        self.assertEqual(expected, config["tools"]["pipx:pytest"]["uvx_args"])
        self.assertEqual(
            expected, lock["tools"]["pipx:pytest"][0]["options"]["uvx_args"]
        )

    def test_runner_delegates_parallel_reporting_to_pytest(self) -> None:
        runner = (ROOT / "scripts/test").read_text()

        self.assertIn('pytest_args="-n $jobs --dist loadfile', runner)
        self.assertIn("--instafail", runner)
        self.assertIn("export PYTHONUNBUFFERED=1", runner)
        self.assertIn('uvx --from "$pytest_requirement"', runner)
        self.assertNotIn('python3 "$test_file"', runner)

    def test_container_suite_uses_the_same_runner(self) -> None:
        container_test = (ROOT / "scripts/setup/container_test.sh").read_text()

        self.assertIn("scripts/test --jobs 4", container_test)
        self.assertNotIn("python3 scripts/setup/setup_test.py", container_test)


if __name__ == "__main__":
    unittest.main()
