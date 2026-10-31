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
        self.checkout = self.directory / "dotfiles with spaces"
        source = self.checkout / "config/mise.toml"
        source.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "config/mise.toml", source)
        self.config = self.directory / "config.toml"
        self.config.symlink_to(source)
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

    def run_mise(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [MISE, *arguments], cwd=cwd or self.directory, env=self.env,
            capture_output=True, text=True, check=False, timeout=30,
        )

    def assert_report(self, result: subprocess.CompletedProcess[str], executable: Path,
                      arguments: list[str]) -> None:
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual([str(executable), arguments], json.loads(result.stdout))

    def test_global_settings_allow_one_off_tools_but_explicit_locked_mode_still_works(self) -> None:
        config = tomllib.loads(self.config.read_text())
        self.assertTrue(config["settings"]["lockfile"])
        unlocked = self.run_mise("settings", "locked")
        self.assertEqual(0, unlocked.returncode, unlocked.stdout + unlocked.stderr)
        self.assertEqual("false", unlocked.stdout.strip())
        locked = self.run_mise("--locked", "settings", "locked")
        self.assertEqual(0, locked.returncode, locked.stdout + locked.stderr)
        self.assertEqual("true", locked.stdout.strip())

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

    def test_fresh_shells_remove_stale_python_shims_and_keep_managed_tools(self) -> None:
        home = self.directory / "home"
        native_bin = home / ".local/bin"
        native_bin.mkdir(parents=True)
        native_python = native_bin / "python3"
        native_python.symlink_to(sys.executable)
        (home / ".profile").symlink_to(ROOT / "config/profile")
        shims = home / ".local/share/mise/shims"
        self.install_wrapper(shims / "python3")
        node_version = tomllib.loads((self.directory / "mise.lock").read_text())["tools"]["node"][0]["version"]
        node_bin = self.data / "installs/node" / node_version / "bin"
        node_bin.mkdir(parents=True)
        (node_bin / "node").symlink_to(sys.executable)
        config = tomllib.loads(self.config.read_text())
        environment = self.env | {
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
            "SSH_AUTH_SOCK": "present", "TERM": "dumb",
            "MISE_DISABLE_TOOLS": ",".join(tool for tool in config["tools"] if tool not in ("python", "node")),
        }
        for shell in ("sh", "bash", "zsh", "fish"):
            executable = shutil.which(shell)
            if executable is None:
                continue
            if shell == "fish":
                command = ['-c', 'source "$PROFILE_FISH"; or exit; command -s python3; command -s node']
            else:
                command = ['-c', '. "$HOME/.profile" || exit; command -v python3; command -v node']
            native_resolution = None
            for inherited_shims in (False, True):
                path = os.pathsep.join((str(Path(MISE).parent), "/usr/bin", "/bin"))
                if inherited_shims:
                    path = os.pathsep.join((str(shims), path, str(shims)))
                with self.subTest(shell=shell, inherited_shims=inherited_shims):
                    result = subprocess.run(
                        [executable, *command], cwd=self.directory,
                        env=environment | {"PROFILE_FISH": str(ROOT / "config/config.fish"), "PATH": path},
                        text=True, capture_output=True, timeout=30,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    resolutions = result.stdout.splitlines()
                    self.assertEqual(2, len(resolutions))
                    self.assertNotIn(str(shims), resolutions[0])
                    self.assertNotIn(str(self.data), resolutions[0])
                    if native_resolution is None:
                        native_resolution = resolutions[0]
                    self.assertEqual([native_resolution, str(node_bin / "node")], resolutions)

    def test_pi_install_finds_checkout_from_symlinked_config_in_any_directory(self) -> None:
        installer = self.checkout / "libexec/setup/install_pi.py"
        installer.parent.mkdir(parents=True)
        # Replace the installer only in disposable storage; never run a real installation.
        installer.write_text(REPORT + "\n")
        for cwd in (self.checkout, installer.parent, self.directory):
            with self.subTest(cwd=cwd):
                self.assert_report(self.run_mise("run", "pi-install", cwd=cwd), self.bootstrap, [])
        installer.write_text("raise SystemExit(7)\n")
        result = self.run_mise("run", "pi-install")
        self.assertEqual(7, result.returncode, result.stdout + result.stderr)

    def test_changing_bootstrap_version_updates_both_tasks_without_consumer_edits(self) -> None:
        original = tomllib.loads(self.config.read_text())["vars"]["bootstrap_python"]
        self.config.write_text(self.config.read_text().replace(
            'bootstrap_python = ' + json.dumps(original), 'bootstrap_python = "3.13.0"',
        ))
        alternate = self.install_python("3.13.0")
        self.assert_report(self.run_mise("run", "bootstrap-python", "--", "-c", REPORT), alternate, [])
        installer = self.checkout / "libexec/setup/install_pi.py"
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
