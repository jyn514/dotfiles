import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


glide = load("glide_setup", "libexec/setup/glide.py")
mimetypes = load("setup_mimetypes", "libexec/setup/setup_mimetypes.py")


class GlideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="glide test ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.data = self.directory / "data"
        self.config = self.directory / "config"
        self.native = self.directory / "glide-bin"
        self.environment = mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_DATA_DIRS": str(self.directory / "system"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_native_selection_disables_mise_and_removal_restores_fallback(self):
        self.native.write_text("#!/bin/sh\n")
        self.native.chmod(0o755)
        with mock.patch.object(glide, "NATIVE_EXECUTABLE", self.native):
            self.assertEqual(glide.GLIDE_TOOL, glide.configure_mise())
            self.assertEqual(glide.GLIDE_TOOL, glide.configure_mise())
            config = self.config / "mise/conf.d/dotfiles-glide.toml"
            self.assertIn(glide.GLIDE_TOOL, config.read_text())
            if mise := shutil.which("mise"):
                environment = os.environ.copy()
                for key in ("MISE_GLOBAL_CONFIG_FILE", "MISE_CONFIG_DIR", "MISE_DISABLE_TOOLS"):
                    environment.pop(key, None)
                environment["MISE_CONFIG_DIR"] = str(self.config / "mise")
                (self.config / "mise/config.toml").symlink_to(ROOT / "config/mise.toml")
                result = subprocess.run(
                    [mise, "ls", "--current", glide.GLIDE_TOOL, "--json"],
                    cwd=self.directory, env=environment, text=True, capture_output=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([], json.loads(result.stdout))
                self.assertNotIn("deprecated", result.stderr)
            self.native.unlink()
            self.assertEqual("", glide.configure_mise())
            self.assertFalse(config.exists())

    def test_native_desktop_wins_over_mise(self):
        desktop = self.data / "applications/glide-browser-bin.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text("[Desktop Entry]\n")
        with mock.patch.object(mimetypes, "command_exists", return_value=True), \
             mock.patch.object(mimetypes.subprocess, "run") as run:
            self.assertEqual("glide-browser-bin.desktop", mimetypes.glide_desktop(False))
        run.assert_not_called()

    def test_native_entry_repairs_xdg_mime_quoting_without_changing_package_files(self):
        native = self.directory / "system/applications/glide-browser-bin.desktop"
        native.parent.mkdir(parents=True)
        content = ('[Desktop Entry]\nType=Application\nName=Glide Browser\n'
                   'Exec=/usr/bin/"glide-bin" %u\nComment=first\nComment=last\n'
                   'StartupWMClass=first\nStartupWMClass=last\n')
        native.write_text(content)
        with mock.patch.object(mimetypes, "command_exists", side_effect=lambda name: name == "glide-bin"):
            mimetypes.glide_desktop(True)
            self.assertFalse(self.data.exists())
            mimetypes.glide_desktop(False)
            mimetypes.glide_desktop(False)
        desktop = self.data / "applications" / native.name
        self.assertEqual(content, native.read_text())
        self.assertIn("Exec=/usr/bin/glide-bin %u\n", desktop.read_text())
        self.assertEqual(1, desktop.read_text().count("Comment="))
        self.assertIn("Comment=last\n", desktop.read_text())
        if validator := shutil.which("desktop-file-validate"):
            result = subprocess.run([validator, str(desktop)], text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        config = self.config / "mimeapps.list"
        config.parent.mkdir(parents=True)
        config.write_text("[Default Applications]\ntext/html=glide-browser-bin.desktop\n")
        result = subprocess.run(["xdg-mime", "query", "default", "text/html"],
                                env=os.environ, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("glide-browser-bin.desktop", result.stdout.strip())
        # A package update must replace the overlay's old arguments too.
        native.write_text(content.replace('Exec=/usr/bin/"glide-bin" %u', 'Exec=/usr/bin/glide-bin --new-window %u'))
        with mock.patch.object(mimetypes, "command_exists", side_effect=lambda name: name == "glide-bin"):
            mimetypes.glide_desktop(False)
        self.assertIn("Exec=/usr/bin/glide-bin --new-window %u", desktop.read_text())

    def test_fallback_desktop_launches_without_shell_activation(self):
        mise = self.directory / "mise"
        log = self.directory / "launch.json"
        fixture = ROOT / "tests/setup/fixtures/glide-mise.py"
        subprocess.run(["cp", str(fixture), str(mise)], check=True)
        subprocess.run(["cmp", str(fixture), str(mise)], check=True)
        mise.chmod(0o755)
        additional_mime = "text/x-browser-test"
        with mock.patch.object(mimetypes, "BROWSER_MIMES", (*mimetypes.BROWSER_MIMES, additional_mime)), \
             mock.patch.object(mimetypes.shutil, "which", return_value=str(mise)), \
             mock.patch.object(mimetypes, "command_exists", return_value=False), \
             mock.patch.object(mimetypes.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 0, str(mise))):
            name = mimetypes.glide_desktop(False)
        desktop = self.data / "applications" / name
        self.assertIn(additional_mime + ";", desktop.read_text())
        command = next(line[5:] for line in desktop.read_text().splitlines()
                       if line.startswith("Exec="))
        target = "file:///tmp/a%20file.html"
        result = subprocess.run(shlex.split(command.replace("%u", target)),
                                env={"PATH": "/usr/bin:/bin", "GLIDE_TEST_LOG": str(log)})
        self.assertEqual(0, result.returncode)
        self.assertEqual([["exec", "--", "glide", target], "0"], json.loads(log.read_text()))

    def test_failed_mise_lookup_does_not_register_a_launcher(self):
        with mock.patch.object(mimetypes, "command_exists", return_value=False), \
             mock.patch.object(mimetypes.shutil, "which", return_value="mise"), \
             mock.patch.object(mimetypes.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 1, "/usr/bin/true")):
            self.assertIsNone(mimetypes.glide_desktop(False))
        self.assertFalse(self.data.exists())

    def test_browser_registration_restores_html_after_editor_defaults(self):
        calls = []
        additional_mime = "text/x-browser-test"
        with mock.patch.object(mimetypes, "BROWSER_MIMES", (*mimetypes.BROWSER_MIMES, additional_mime)), \
             mock.patch.object(mimetypes, "discover_editor_mimes", return_value=["text/html"]), \
             mock.patch.object(mimetypes, "write_linux_desktop"), \
             mock.patch.object(mimetypes, "command_exists", return_value=False), \
             mock.patch.object(mimetypes, "glide_desktop", return_value="glide-browser-bin.desktop"), \
             mock.patch.object(mimetypes, "run", side_effect=lambda argv: calls.append(argv)):
            for _ in range(2):
                mimetypes.linux_setup({"linux": {}}, False)
        for mime in ("text/html", "application/xhtml+xml", "image/svg+xml", additional_mime,
                     "x-scheme-handler/http", "x-scheme-handler/https"):
            registrations = [argv[2] for argv in calls if argv[:2] == ["xdg-mime", "default"]
                             and argv[-1] == mime]
            self.assertEqual("glide-browser-bin.desktop", registrations[-1])
        self.assertEqual(2, calls.count(["xdg-mime", "default", "nvim-generated.desktop", "text/html"]))


class GlideInstallerTests(unittest.TestCase):
    def run_installer(self, commands, **overrides):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binaries = directory / "bin"
            binaries.mkdir()
            recorder = binaries / "record"
            fixture = ROOT / "tests/setup/fixtures/glide-package-command.sh"
            subprocess.run(["cp", str(fixture), str(recorder)], check=True)
            subprocess.run(["cmp", str(fixture), str(recorder)], check=True)
            recorder.chmod(0o755)
            for command in commands:
                (binaries / command).symlink_to(recorder)
            log = directory / "commands.log"
            for name in ("lib", "libexec", "config"):
                (directory / name).symlink_to(ROOT / name, target_is_directory=True)
            source = (ROOT / "setup").read_text()
            entrypoint = (ROOT / "tests/setup/fixtures/glide-native-entrypoint.sh").read_text()
            script = directory / "setup"
            script.write_text(source.replace('if ! [ $# = 0 ]; then\n', entrypoint + '\nif ! [ $# = 0 ]; then\n', 1))
            environment = os.environ.copy()
            environment.update(HOME=str(directory), PATH=f"{binaries}:/usr/bin:/bin",
                               GLIDE_TEST_BIN=str(binaries), GLIDE_TEST_LOG=str(log),
                               GLIDE_TEST_PLATFORM="linux")
            environment.update(overrides)
            result = subprocess.run(["sh", str(script)], cwd=directory, env=environment,
                                    text=True, capture_output=True)
            return result, log.read_text().splitlines() if log.exists() else []

    def test_installed_native_package_does_not_install_another_copy(self):
        result, commands = self.run_installer(["pacman", "paru"], GLIDE_TEST_INSTALLED="0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["pacman <-Q> <glide-browser-bin>"], commands)

    def test_repository_package_is_preferred_to_aur_helpers(self):
        result, commands = self.run_installer(["pacman", "sudo", "paru"], GLIDE_TEST_REPOSITORY="0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("sudo <pacman> <-S> <--needed> <glide-browser-bin>", commands[-1])

    def test_aur_uses_an_existing_helper_and_propagates_failure(self):
        for helper in ("paru", "yay"):
            for status in ("0", "1"):
                with self.subTest(helper=helper, status=status):
                    result, commands = self.run_installer(["pacman", helper], GLIDE_TEST_INSTALL_STATUS=status)
                    self.assertEqual(int(status), result.returncode, result.stderr)
                    self.assertEqual(f"{helper} <-S> <--needed> <glide-browser-bin>", commands[-1])

    def test_missing_aur_helper_reports_the_required_package(self):
        result, commands = self.run_installer(["pacman"])
        self.assertEqual(1, result.returncode)
        self.assertIn("glide-browser-bin from the AUR", result.stderr)
        self.assertEqual(2, len(commands))

    def test_other_linux_hosts_leave_installation_to_mise(self):
        result, commands = self.run_installer([])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], commands)

    def test_macos_installs_the_browser_cask(self):
        result, commands = self.run_installer(["brew"], GLIDE_TEST_PLATFORM="macos")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("brew <install> <--cask> <glide-browser>", commands)


if __name__ == "__main__":
    unittest.main()
