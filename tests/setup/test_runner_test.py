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

    def run_native_containers(self, *, metadata=None, containers=True,
                              pytest_status=0, probe_status=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "dev/test", "dev/test-environment",
                "tools/codex-sandbox/owned_images.py",
                "tests/fixtures/native_test_runner_command.sh",
            ):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["cp", ROOT / relative, destination], check=True)
                subprocess.run(["cmp", ROOT / relative, destination], check=True)
            home = root / "host-home"
            home.mkdir()
            if metadata is not None:
                marker = home / ".local/share/pi/node/.source-revision"
                marker.parent.mkdir(parents=True)
                marker.write_bytes(metadata)
            binaries = root / "bin"
            binaries.mkdir()
            fixture = root / "tests/fixtures/native_test_runner_command.sh"
            for command in ("pytest", "bb", "node", "bun", "cargo", "python3",
                            "java", "jj", "rg"):
                (binaries / command).symlink_to(fixture)
            container_driver = root / "dev/setup/container-test"
            container_driver.parent.mkdir()
            container_driver.symlink_to(fixture)
            log = root / "commands.log"
            environment = os.environ | {
                "HOME": str(home), "PATH": f"{binaries}:{os.environ['PATH']}",
                "TEST_LOG": str(log), "TEST_PYTHON_REAL": shutil.which("python3"),
                "TEST_PYTEST_STATUS": str(pytest_status),
                "TEST_PROBE_STATUS": str(probe_status),
                # A stale inherited capture must never replace the actual marker.
                "DOTFILES_TEST_PI_REVISION": "f" * 40,
            }
            for tool in ("BB", "JAVA", "JJ", "RG"):
                environment[f"DOTFILES_TEST_{tool}_REAL"] = str(binaries / tool.lower())
            result = subprocess.run(
                [root / "dev/test", *(["--containers"] if containers else [])],
                cwd=root, env=environment, text=True, capture_output=True, check=False,
            )
            commands = log.read_text().splitlines() if log.exists() else []
            return result, commands, str(home)

    def test_native_containers_capture_installed_revision_before_isolation(self) -> None:
        revision = "0123456789abcdef" * 2 + "01234567"
        result, commands, host_home = self.run_native_containers(
            metadata=(revision + "\n").encode("ascii"),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        helper = Path(host_home).parent / "tools/codex-sandbox/owned_images.py"
        self.assertEqual(
            [f"metadata-home <{host_home}>", f"metadata-helper <{helper}>"], commands[:2],
        )
        self.assertEqual(1, sum(line.startswith("metadata-helper") for line in commands))
        dispatch = next(line for line in commands if line.startswith("dispatch-home"))
        private_home = dispatch.removeprefix("dispatch-home <").removesuffix(">")
        self.assertNotEqual(host_home, private_home)
        self.assertFalse(Path(private_home).exists())
        self.assertIn(
            "python3 <tools/codex-sandbox/tests/image_runtime_integration.py> "
            f"<--expected-revision> <{revision}>", commands,
        )
        self.assertEqual(4, sum(line.startswith("container-test ") for line in commands))
        self.assertIn("All checks and 4 container suites passed", result.stdout)

    def test_native_containers_reject_missing_or_invalid_installed_metadata(self) -> None:
        for metadata, diagnostic in (
            (None, "Cannot read installed Pi revision"),
            (b"not-a-commit\n", "Invalid installed Pi revision"),
            (b"\xff", "Cannot read installed Pi revision"),
        ):
            with self.subTest(metadata=metadata):
                result, commands, host_home = self.run_native_containers(metadata=metadata)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertEqual(1, result.stderr.count(diagnostic))
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn(f"{host_home}/.local/share/pi/node/.source-revision", result.stderr)
                self.assertIn("run mise run pi-install", result.stderr)
                helper = Path(host_home).parent / "tools/codex-sandbox/owned_images.py"
                self.assertEqual(
                    [f"metadata-home <{host_home}>", f"metadata-helper <{helper}>"], commands,
                )

    def test_native_without_containers_does_not_require_installed_metadata(self) -> None:
        result, commands, _ = self.run_native_containers(containers=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(line.startswith("metadata-") for line in commands))
        self.assertTrue(any(line.startswith("dispatch-home") for line in commands))
        self.assertFalse(any("image_runtime_integration.py" in line for line in commands))
        self.assertIn("All checks passed", result.stdout)

    def test_native_containers_preserve_test_and_probe_failure_status(self) -> None:
        for pytest_status, probe_status in ((23, 0), (0, 31)):
            with self.subTest(pytest_status=pytest_status, probe_status=probe_status):
                result, commands, _ = self.run_native_containers(
                    metadata=b"a" * 40, pytest_status=pytest_status, probe_status=probe_status,
                )
                self.assertEqual(pytest_status or probe_status, result.returncode, result.stderr)
                self.assertFalse(any(line.startswith("container-test ") for line in commands))
                if pytest_status:
                    self.assertFalse(any("image_runtime_integration.py" in line for line in commands))
                self.assertNotIn("All checks", result.stdout)

    def test_rejects_invalid_job_counts_before_dispatch(self) -> None:
        result = subprocess.run(
            [ROOT / "dev/test", "--jobs", "0"], text=True, capture_output=True
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("positive integer", result.stderr)


if __name__ == "__main__":
    unittest.main()
