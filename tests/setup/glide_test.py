import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
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
open_fastmail = load("open_fastmail", "libexec/setup/open_fastmail.py")


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
        # xdg-mime checks that Exec names an installed executable. Keep the
        # package-path assertions above, but query a disposable copy so this
        # regression does not require Glide installed in /usr/bin. This path
        # has no spaces: the malformed quoting under test is the basename's.
        with tempfile.TemporaryDirectory(prefix="glide-xdg-") as temporary:
            data = Path(temporary)
            executable = data / "glide-bin"
            executable.symlink_to(shutil.which("true"))
            query_desktop = data / "applications" / desktop.name
            query_desktop.parent.mkdir()
            subprocess.run(["cp", str(desktop), str(query_desktop)], check=True)
            subprocess.run(["cmp", str(desktop), str(query_desktop)], check=True)
            repaired = query_desktop.read_text().replace("/usr/bin/glide-bin", str(executable))
            environment = dict(os.environ, XDG_DATA_HOME=str(data),
                               XDG_CURRENT_DESKTOP="X-Generic")
            for command, expected in ((f'{data}/"glide-bin"', ""),
                                      (str(executable), desktop.name)):
                with self.subTest(command=command):
                    query_desktop.write_text(repaired.replace(str(executable), command))
                    result = subprocess.run(["xdg-mime", "query", "default", "text/html"],
                                            env=environment, text=True, capture_output=True)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(expected, result.stdout.strip())
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

    def test_mail_launcher_opens_fastmail_compose_in_glide(self):
        applications = self.data / "applications"
        applications.mkdir(parents=True)
        with mock.patch.object(mimetypes, "command_exists", return_value=False):
            name = mimetypes.glide_mail_desktop(False)
        mail = applications / name
        self.assertIn(
            f"Exec={self.data}/dotfiles/open-fastmail %u\n",
            mail.read_text(),
        )
        self.assertIn("MimeType=x-scheme-handler/mailto;\n", mail.read_text())
        launcher = self.data / "dotfiles/open-fastmail"
        self.assertEqual((ROOT / "libexec/setup/open_fastmail.py").read_text(),
                         launcher.read_text())
        self.assertTrue(os.access(launcher, os.X_OK))
        if validator := shutil.which("desktop-file-validate"):
            result = subprocess.run(
                [validator, str(mail)], text=True, capture_output=True
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_mail_launcher_encodes_the_complete_mailto_uri(self):
        self.assertEqual(
            "https://app.fastmail.com/mail/compose?mailto="
            "mailto%3Afriend%40example.com%3Fsubject%3Dtwo%2520words%26body%3Done%2520line",
            open_fastmail.fastmail_compose(
                "mailto:friend@example.com?subject=two%20words&body=one%20line"
            ),
        )
        with self.assertRaisesRegex(ValueError, "expected a mailto URI"):
            open_fastmail.fastmail_compose("https://example.com")

    @unittest.skipUnless(shutil.which("gio"), "gio is not installed")
    def test_desktop_runtime_passes_mailto_to_fastmail_launcher(self):
        with tempfile.TemporaryDirectory(prefix="glide-mail-") as temporary:
            directory = Path(temporary)
            data = directory / "data"
            applications = data / "applications"
            applications.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(data)}), \
                 mock.patch.object(mimetypes, "command_exists", return_value=False):
                name = mimetypes.glide_mail_desktop(False)
            binaries = directory / "bin"
            binaries.mkdir()
            recorder = ROOT / "tests/setup/fixtures/xdg-open-recorder.py"
            xdg_open = binaries / "xdg-open"
            xdg_open.symlink_to(recorder)
            log = directory / "xdg-open.json"
            mailto = "mailto:friend@example.com?subject=two%20words"
            environment = dict(
                os.environ,
                PATH=f"{binaries}:{os.environ['PATH']}",
                XDG_OPEN_TEST_LOG=str(log),
            )
            result = subprocess.run(
                ["gio", "launch", str(applications / name), mailto],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            deadline = time.monotonic() + 2
            while not log.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(log.exists(), "desktop launcher did not invoke xdg-open")
            self.assertEqual(
                [
                    str(xdg_open),
                    "https://app.fastmail.com/mail/compose?mailto="
                    "mailto%3Afriend%40example.com%3Fsubject%3Dtwo%2520words",
                ],
                json.loads(log.read_text()),
            )

    def test_browser_registration_restores_html_after_editor_defaults(self):
        calls = []
        additional_mime = "text/x-browser-test"
        with mock.patch.object(mimetypes, "BROWSER_MIMES", (*mimetypes.BROWSER_MIMES, additional_mime)), \
             mock.patch.object(mimetypes, "discover_editor_mimes", return_value=["text/html"]), \
             mock.patch.object(mimetypes, "write_linux_desktop"), \
             mock.patch.object(mimetypes, "command_exists", return_value=False), \
             mock.patch.object(mimetypes, "glide_desktop", return_value="glide-browser-bin.desktop"), \
             mock.patch.object(mimetypes, "glide_mail_desktop", return_value="fastmail-glide.desktop"), \
             mock.patch.object(mimetypes, "run", side_effect=lambda argv: calls.append(argv)):
            for _ in range(2):
                mimetypes.linux_setup({"linux": {}}, False)
        for mime in ("text/html", "application/xhtml+xml", "image/svg+xml", additional_mime,
                     "x-scheme-handler/http", "x-scheme-handler/https"):
            registrations = [argv[2] for argv in calls if argv[:2] == ["xdg-mime", "default"]
                             and argv[-1] == mime]
            self.assertEqual("glide-browser-bin.desktop", registrations[-1])
        self.assertEqual(2, calls.count(["xdg-mime", "default", "nvim-generated.desktop", "text/html"]))
        self.assertEqual(2, calls.count(["xdg-mime", "default", "fastmail-glide.desktop",
                                        "x-scheme-handler/mailto"]))


class NativePackageInstallerTests(unittest.TestCase):
    def run_installer(self, commands, entrypoint="glide-native-entrypoint.sh", **overrides):
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
            test_entrypoint = (ROOT / "tests/setup/fixtures" / entrypoint).read_text()
            script = directory / "setup"
            script.write_text(source.replace('if ! [ $# = 0 ]; then\n', test_entrypoint + '\nif ! [ $# = 0 ]; then\n', 1))
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

    def test_dragon_installs_from_aur_on_arch(self):
        for helper in ("paru", "yay"):
            with self.subTest(helper=helper):
                result, commands = self.run_installer(
                    ["pacman", helper], entrypoint="dragon-native-entrypoint.sh")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(f"{helper} <-S> <--needed> <dragon-drop>", commands[-1])

    def test_dragon_prefers_yay_when_both_helpers_are_installed(self):
        result, commands = self.run_installer(
            ["pacman", "paru", "yay"], entrypoint="dragon-native-entrypoint.sh")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("yay <-S> <--needed> <dragon-drop>", commands[-1])

    def test_installed_dragon_does_not_install_another_copy(self):
        result, commands = self.run_installer(
            ["pacman", "paru"], entrypoint="dragon-native-entrypoint.sh",
            GLIDE_TEST_INSTALLED="0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["pacman <-Q> <dragon-drop>"], commands)

    def test_missing_aur_helper_reports_dragon_package(self):
        result, commands = self.run_installer(
            ["pacman"], entrypoint="dragon-native-entrypoint.sh")
        self.assertEqual(1, result.returncode)
        self.assertIn("dragon-drop from the AUR", result.stderr)
        self.assertEqual(["pacman <-Q> <dragon-drop>"], commands)

    def test_non_arch_hosts_skip_dragon(self):
        result, commands = self.run_installer(
            [], entrypoint="dragon-native-entrypoint.sh")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], commands)


if __name__ == "__main__":
    unittest.main()
