#!/usr/bin/env python3

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestRunnerTests(unittest.TestCase):
    def run_fallback(self, *, missing_plugin=False, uv_available=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev").mkdir()
            (root / "dev/test").write_bytes((ROOT / "dev/test").read_bytes())
            (root / "install").mkdir()
            (root / "install/test.txt").write_bytes((ROOT / "install/test.txt").read_bytes())
            bin_directory = root / "bin"
            bin_directory.mkdir()
            for command in ("dirname", "mktemp", "date", "grep", "rm"):
                (bin_directory / command).symlink_to(shutil.which(command))
            log = root / "uvx.args"
            if missing_plugin:
                pytest = bin_directory / "pytest"
                pytest.write_text(
                    "#!/bin/sh\n"
                    "if [ \"${1-}\" = --help ]; then\n"
                    "  echo '--instafail --numprocesses'\n"
                    "  exit 0\n"
                    "fi\n"
                    "exit 99\n"
                )
                pytest.chmod(0o755)
            if uv_available:
                for command in ("uv", "uvx"):
                    executable = bin_directory / command
                    executable.write_text(
                        "#!/bin/sh\n"
                        "printf '%s\\n' \"$@\" > \"$TEST_LOG\"\n"
                        "exit 23\n"
                    )
                    executable.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", root / "dev/test", "--test-environment-ready", "--jobs", "3"],
                cwd=root,
                env=os.environ | {"PATH": str(bin_directory), "TEST_LOG": str(log)},
                text=True,
                capture_output=True,
            )
            return result, log.read_text().splitlines() if log.exists() else []

    def test_missing_global_pytest_uses_pinned_requirements(self) -> None:
        result, arguments = self.run_fallback()
        self.assertEqual(23, result.returncode, result.stderr)
        requirements = (ROOT / "install/test.txt").read_text().splitlines()
        self.assertEqual(
            ["--from", requirements[0], "--with", requirements[1],
             "--with", requirements[2], "--with", requirements[3], "pytest"],
            arguments[:9],
        )
        self.assertEqual("3", arguments[arguments.index("-n") + 1])
        self.assertIn("--instafail", arguments)

    def test_installed_pytest_missing_a_plugin_uses_uvx(self) -> None:
        result, arguments = self.run_fallback(missing_plugin=True)
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertIn("pytest", arguments)

    def test_missing_uv_explains_how_to_get_pinned_test_dependencies(self) -> None:
        result, arguments = self.run_fallback(uv_available=False)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("install uv", result.stderr)
        self.assertIn("install/test.txt", result.stderr)
        self.assertEqual([], arguments)

    def test_jobs_are_dispatched_to_pytest_and_failures_are_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dev").mkdir()
            for name in ("test", "test-environment"):
                (root / f"dev/{name}").write_bytes((ROOT / f"dev/{name}").read_bytes())
                (root / f"dev/{name}").chmod(0o755)
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

    def test_pi_suite_is_dispatched_and_its_failure_stops_the_runner(self) -> None:
        for status in (0, 29):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "dev").mkdir()
                runner = root / "dev/test"
                subprocess.run(["cp", ROOT / "dev/test", runner], check=True)
                subprocess.run(["cmp", ROOT / "dev/test", runner], check=True)
                binaries = root / "bin"
                binaries.mkdir()
                for command in ("pytest", "bb", "node", "bun", "cargo", "python3"):
                    (binaries / command).symlink_to(ROOT / "tests/fixtures/test_runner_command.sh")
                log = root / "commands.log"
                environment = {
                    key: value for key, value in os.environ.items()
                    if key not in ("DOTFILES_TEST_BB_REAL", "DOTFILES_TEST_JJ_REAL")
                }
                environment.update(
                    PATH=f"{binaries}:{environment['PATH']}", TEST_LOG=str(log),
                    PI_TEST_STATUS=str(status),
                )
                result = subprocess.run(
                    ["/bin/sh", runner, "--test-environment-ready"], cwd=root,
                    env=environment, text=True, capture_output=True, check=False,
                )
                self.assertEqual(status, result.returncode, result.stderr)
                commands = log.read_text().splitlines()
                self.assertEqual(1, commands.count("bun <test> <tests/pi>"))
                later_suite = "bun <test> <tools/codex-sandbox/tests/guest_tools_test.ts>"
                if status:
                    self.assertNotIn(later_suite, commands)
                else:
                    self.assertIn(later_suite, commands)
                    self.assertIn("All checks passed", result.stdout)

    def test_rejects_invalid_job_counts_before_dispatch(self) -> None:
        result = subprocess.run(
            [ROOT / "dev/test", "--jobs", "0"], text=True, capture_output=True
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("positive integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
