#!/usr/bin/env python3
"""Exercise task-only Python selection with real mise and disposable interpreters."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MISE = shutil.which("mise")
REPORT = "import os, sys, json; print(json.dumps([os.environ['DOTFILES_PYTHON_EXECUTABLE'], sys.argv[1:]]))"


@unittest.skipUnless(MISE and os.name == "posix", "requires mise and POSIX shell")
class MisePythonScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.directory = Path(self.tempdir.name)
        self.config = self.directory / "config.toml"
        shutil.copyfile(ROOT / "config/mise.toml", self.config)
        shutil.copyfile(ROOT / "config/mise.lock", self.directory / "mise.lock")
        config = tomllib.loads(self.config.read_text())
        lock = tomllib.loads((self.directory / "mise.lock").read_text())
        self.version = lock["tools"]["python"][0]["version"]
        self.data = self.directory / "data"
        self.bootstrap = self.install_python(self.version)
        self.system = self.install_wrapper(self.directory / "bin/python")
        self.env = os.environ | {
            "MISE_GLOBAL_CONFIG_FILE": str(self.config),
            "MISE_DATA_DIR": str(self.data),
            "MISE_CACHE_DIR": str(self.directory / "cache"),
            "MISE_AUTO_INSTALL": "0",
            "MISE_NO_REMOTE": "1",
            # These fixtures represent prebuilt installs, not compiled Python builds.
            "MISE_PYTHON_COMPILE": "0",
            # Other runtimes are outside this test's scope, not fake installations.
            "MISE_DISABLE_TOOLS": ",".join(tool for tool in config["tools"] if tool != "python"),
            "DOTFILES_TEST_PYTHON": sys.executable,
            "PATH": str(self.system.parent) + os.pathsep + os.environ["PATH"],
        }

    def install_wrapper(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "tests/setup/fixtures/bootstrap_python.sh", path)
        path.chmod(0o755)
        return path

    def install_python(self, version: str) -> Path:
        return self.install_wrapper(self.data / "installs/python" / version / "bin/python")

    def run_mise(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [MISE, *arguments], cwd=self.directory, env=self.env,
            capture_output=True, text=True, check=False, timeout=30,
        )

    def assert_report(self, result: subprocess.CompletedProcess[str], executable: Path,
                      arguments: list[str]) -> None:
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual([str(executable), arguments], json.loads(result.stdout))

    def test_global_environment_leaves_python_alone_but_bootstrap_selects_locked_python(self) -> None:
        active = self.run_mise("ls", "--current", "--json")
        self.assertEqual(0, active.returncode, active.stdout + active.stderr)
        self.assertNotIn("python", json.loads(active.stdout))
        argument = "spaces, 'quotes', $variables; not shell code"
        self.install_python("99.0.0")  # A newer installation must not override the lock.
        self.assert_report(self.run_mise("exec", "--", "python", "-c", REPORT, argument),
                           self.system, [argument])
        self.assert_report(self.run_mise("run", "bootstrap-python", "--", "-c", REPORT, argument),
                           self.bootstrap, [argument])
        # A completed task must not leave Python active for subsequent commands.
        self.assert_report(self.run_mise("exec", "--", "python", "-c", REPORT), self.system, [])

    def test_pi_install_selects_bootstrap_python_and_preserves_callers_directory(self) -> None:
        installer = self.directory / "libexec/setup/install_pi.py"
        installer.parent.mkdir(parents=True)
        # Replace the installer only in disposable storage; never run a real installation.
        installer.write_text(REPORT + "\n")
        self.assert_report(self.run_mise("run", "pi-install"), self.bootstrap, [])

    def test_changing_bootstrap_version_updates_both_tasks_without_consumer_edits(self) -> None:
        original = tomllib.loads(self.config.read_text())["vars"]["bootstrap_python"]
        self.config.write_text(self.config.read_text().replace(
            'bootstrap_python = ' + json.dumps(original), 'bootstrap_python = "3.13.0"',
        ))
        alternate = self.install_python("3.13.0")
        self.assert_report(self.run_mise("run", "bootstrap-python", "--", "-c", REPORT), alternate, [])
        installer = self.directory / "libexec/setup/install_pi.py"
        installer.parent.mkdir(parents=True)
        installer.write_text(REPORT + "\n")
        self.assert_report(self.run_mise("run", "pi-install"), alternate, [])
        self.assert_report(self.run_mise("exec", "--", "python", "-c", REPORT), self.system, [])

    def test_bootstrap_helper_passes_arguments_and_propagates_failure(self) -> None:
        # Use the production shell function without entering setup's mutating main.
        functions = (ROOT / "setup").read_text().split("install_mise()", 1)[0]
        script = self.directory / "bootstrap-helper.sh"
        script.write_text(functions + '\nbootstrap_python "$@"\n')
        env = self.env | {"MISE_SETUP_CONFIG": str(self.config),
                          "PATH": str(Path(MISE).parent) + os.pathsep + self.env["PATH"]}
        argument = "argument with spaces and 'quotes'"
        result = subprocess.run(["sh", str(script), "-c", REPORT, argument], cwd=self.directory,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assert_report(result, self.bootstrap, [argument])
        result = subprocess.run(["sh", str(script), "-c", "raise SystemExit(7)"], cwd=self.directory,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(7, result.returncode, result.stdout + result.stderr)

    def test_install_prepares_task_python_even_though_it_is_not_globally_active(self) -> None:
        pin = self.run_mise("config", "get", "--file", str(self.config), "vars.bootstrap_python")
        self.assertEqual(0, pin.returncode, pin.stdout + pin.stderr)
        request = "python@" + pin.stdout.strip()
        result = self.run_mise("install", request, "--dry-run-code")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        shutil.rmtree(self.bootstrap.parent.parent)
        result = self.run_mise("install", request, "--dry-run-code")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("ERROR", result.stderr)
        self.assertIn("python", result.stderr)
        self.assertIn(self.version, result.stderr)

    def test_bootstrap_installer_uses_authoritative_pin_and_propagates_failures(self) -> None:
        recorder = self.directory / "recorder/mise"
        recorder.parent.mkdir()
        shutil.copyfile(ROOT / "tests/setup/fixtures/mise_install_recorder.py", recorder)
        recorder.chmod(0o755)
        functions = (ROOT / "setup").read_text().split("install_mise()", 1)[0]
        script = self.directory / "install-helper.sh"
        script.write_text(functions + '\ninstall_bootstrap_python\n')
        env = self.env | {"MISE_SETUP_CONFIG": str(self.config), "DOTFILES_REAL_MISE": MISE,
                          "PATH": str(recorder.parent) + os.pathsep + self.env["PATH"]}
        original = tomllib.loads(self.config.read_text())["vars"]["bootstrap_python"]
        for version in (original, "3.13.0"):
            with self.subTest(version=version):
                self.config.write_text(self.config.read_text().replace(
                    'bootstrap_python = ' + json.dumps(original), 'bootstrap_python = ' + json.dumps(version),
                ))
                result = subprocess.run(["sh", str(script)], cwd=self.directory, env=env,
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(["install", "--yes", "python@" + version], json.loads(result.stdout))
        result = subprocess.run(["sh", str(script)], cwd=self.directory,
                                env=env | {"DOTFILES_INSTALL_EXIT": "9"},
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(9, result.returncode, result.stdout + result.stderr)
        self.config.write_text("[vars]\n")
        result = subprocess.run(["sh", str(script)], cwd=self.directory, env=env,
                                text=True, capture_output=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)  # Failed generation must not invoke installation.


if __name__ == "__main__":
    unittest.main()
