from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "install_pi", ROOT / "libexec/setup/install_pi.py"
)
assert SPEC is not None and SPEC.loader is not None
install_pi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install_pi)


class PiInstallTest(unittest.TestCase):
    def test_matching_marker_does_not_hide_a_missing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            install = state / "node"
            package = install / "node_modules/@earendil-works/pi-coding-agent"
            package.mkdir(parents=True)
            (install / ".source-revision").write_text(
                install_pi.PI_REVISION + "\n", encoding="utf-8"
            )

            with mock.patch.object(install_pi, "PI_INSTALL", install), \
                    mock.patch.object(install_pi, "PI_CLI", install / "node_modules/.bin/pi"):
                self.assertFalse(install_pi.install_is_current(install_pi.PI_REVISION))

    def test_install_records_revision_only_after_npm_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            source = state / "source"
            install = state / "node"
            package = source / "packages/coding-agent"
            package.mkdir(parents=True)

            commands: list[tuple[list[str], Path | None]] = []

            def fake_run(command: list[str], *, cwd: Path | None = None) -> None:
                commands.append((command, cwd))
                if command[:2] == ["git", "clone"]:
                    (source / ".git").mkdir()
                if command[:2] == ["npm", "install"] and "--prefix" in command:
                    cli = install / "node_modules/.bin/pi"
                    cli.parent.mkdir(parents=True, exist_ok=True)
                    cli.touch()
                    installed_package = install / "node_modules/@earendil-works/pi-coding-agent"
                    installed_package.parent.mkdir(parents=True, exist_ok=True)
                    installed_package.symlink_to(package, target_is_directory=True)
                    (package / "README.md").touch()
                    (package / "docs").mkdir()
                    (package / "examples").mkdir()
                if command[0] == "node":
                    self.assertFalse((install / ".source-revision").exists())

            with mock.patch.object(install_pi, "PI_STATE", state), \
                    mock.patch.object(install_pi, "PI_SOURCE", source), \
                    mock.patch.object(install_pi, "PI_INSTALL", install), \
                    mock.patch.object(install_pi, "PI_PACKAGE", package), \
                    mock.patch.object(install_pi, "PI_CLI", install / "node_modules/.bin/pi"), \
                    mock.patch.object(install_pi, "run", side_effect=fake_run), \
                    mock.patch.object(install_pi.subprocess, "run") as subprocess_run:
                subprocess_run.return_value.stdout = "test-revision"
                install_pi.install()

            self.assertEqual("test-revision\n",
                             (install / ".source-revision").read_text(encoding="utf-8"))
            self.assertEqual(["git", "checkout", "--force", "--detach", "FETCH_HEAD"], commands[2][0])
            self.assertEqual(["npm", "run", "hydrate:pinned-model-data"], commands[4][0])
            self.assertEqual(["npm", "run", "build:offline"], commands[5][0])
            self.assertIn("--prefix", commands[6][0])


class PiInstallIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.state = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.source = self.state / "source"
        self.install = self.state / "node"
        self.package = self.source / "packages/coding-agent"
        self.tui = self.source / "packages/tui"
        self.installed_package = (
            self.install / "node_modules/@earendil-works/pi-coding-agent"
        )
        self.marker = self.install / ".source-revision"
        for name, value in {
            "PI_STATE": self.state,
            "PI_SOURCE": self.source,
            "PI_INSTALL": self.install,
            "PI_PACKAGE": self.package,
            "PI_CLI": self.install / "node_modules/.bin/pi",
        }.items():
            self.stack.enter_context(mock.patch.object(install_pi, name, value))
        self.stack.enter_context(mock.patch.object(install_pi, "prepare_source"))
        self.stack.enter_context(
            mock.patch.object(install_pi, "source_revision", return_value="fixture-revision")
        )
        # Exercise an ambient npm setting that packs local packages instead of
        # linking them. The installer must override it without changing user config.
        self.stack.enter_context(mock.patch.dict(os.environ, {
            "npm_config_install_links": "true",
            "npm_config_offline": "true",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
        }))
        fixtures = ROOT / "tests/setup/fixtures/pi-sdk"
        self.package.mkdir(parents=True)
        self.tui.mkdir(parents=True)
        (self.source / "package.json").write_text(json.dumps({
            "name": "pi-install-fixture",
            "private": True,
            "workspaces": ["packages/*"],
            "scripts": {
                "hydrate:pinned-model-data": "node --version",
                "build:offline": "node --version",
            },
        }), encoding="utf-8")
        (self.package / "package.json").write_text(json.dumps({
            "name": "@earendil-works/pi-coding-agent",
            "version": "1.3.0",
            "type": "module",
            "exports": {".": {"import": "./index.mjs"}},
            "bin": {"pi": "./index.mjs"},
            "dependencies": {"@earendil-works/pi-tui": "1.3.0"},
        }), encoding="utf-8")
        (self.tui / "package.json").write_text(json.dumps({
            "name": "@earendil-works/pi-tui",
            "version": "1.3.0",
            "type": "module",
            "main": "./index.mjs",
        }), encoding="utf-8")
        shutil.copyfile(fixtures / "index.mjs", self.package / "index.mjs")
        shutil.copyfile(fixtures / "tui.mjs", self.tui / "index.mjs")
        (self.package / "README.md").touch()
        (self.package / "docs").mkdir()
        (self.package / "examples").mkdir()
        subprocess.run([
            "npm", "install", "--package-lock-only", "--ignore-scripts",
        ], cwd=self.source, check=True, capture_output=True, text=True)

    def copied_installation(self) -> None:
        shutil.copytree(self.package, self.installed_package)
        installed_tui = self.installed_package.parent / "pi-tui"
        shutil.copytree(self.tui, installed_tui)
        shutil.copyfile(
            ROOT / "tests/setup/fixtures/pi-sdk/old-tui.mjs",
            installed_tui / "index.mjs",
        )
        cli = self.install / "node_modules/.bin/pi"
        cli.parent.mkdir(parents=True)
        cli.symlink_to(self.installed_package / "index.mjs")
        self.marker.write_text("fixture-revision\n", encoding="utf-8")

    def test_matching_marker_does_not_accept_a_copied_sdk(self) -> None:
        self.copied_installation()
        self.assertFalse(install_pi.install_is_current("fixture-revision"))

    def test_repairs_a_copied_sdk_despite_ambient_install_links(self) -> None:
        self.copied_installation()
        install_pi.install()
        self.assertTrue(self.installed_package.is_symlink())
        self.assertEqual(self.package, self.installed_package.resolve())
        self.assertTrue(install_pi.install_is_current("fixture-revision"))
        self.assertEqual("fixture-revision\n", self.marker.read_text(encoding="utf-8"))
        with mock.patch.object(install_pi, "run", wraps=install_pi.run) as run:
            install_pi.install()
        self.assertFalse(any(call.args[0][0] == "npm" for call in run.call_args_list))

    def test_broken_public_import_is_not_recorded_as_success(self) -> None:
        shutil.copyfile(
            ROOT / "tests/setup/fixtures/pi-sdk/old-tui.mjs",
            self.tui / "index.mjs",
        )
        with self.assertRaises(subprocess.CalledProcessError) as error:
            install_pi.install()
        self.assertEqual("node", error.exception.cmd[0])
        self.assertFalse(self.marker.exists())
        # A matching old receipt must not hide a now-broken linked build either.
        self.marker.write_text("fixture-revision\n", encoding="utf-8")
        self.assertFalse(install_pi.install_is_current("fixture-revision"))


if __name__ == "__main__":
    unittest.main()
