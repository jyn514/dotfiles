"""Check desktop overrides against native files and a real GIO launch."""
import configparser
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("private_mimetypes", ROOT / "libexec/setup/setup_mimetypes.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PrivateDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="private desktop ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.config = self.root / "config"
        self.system = self.root / "system/applications"
        self.system.mkdir(parents=True)
        self.bin = self.root / "checkout/bin"
        self.bin.mkdir(parents=True)
        for name in ("glide-bin", "1password"):
            (self.bin / name).symlink_to(ROOT / "tests/setup/fixtures/xdg-open-recorder.py")
        self.environment = {
            "XDG_DATA_HOME": str(self.data), "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_DIRS": str(self.system.parent),
        }
        env = patch.dict(os.environ, self.environment)
        env.start()
        self.addCleanup(env.stop)
        root = patch.object(setup, "ROOT", self.bin.parent)
        root.start()
        self.addCleanup(root.stop)
        commands = patch.object(setup, "command_exists", side_effect=lambda name: name == "glide-bin")
        commands.start()
        self.addCleanup(commands.stop)

    def entry(self, path):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read(path)
        return parser

    def test_glide_routes_all_actions_and_keeps_native_updates(self):
        source = self.system / "glide-browser-bin.desktop"
        native = (
            '[Desktop Entry]\nName=Glide\nType=Application\nExec=/usr/bin/"glide-bin" %u\n'
            'Actions=new-window;new-private-window;profile-manager;\n'
            '[Desktop Action new-window]\nName=New window\nExec=/usr/bin/"glide-bin" --new-window %u\n'
            '[Desktop Action new-private-window]\nName=Private\nExec=/usr/bin/glide-bin --private-window %u\n'
            '[Desktop Action profile-manager]\nName=Profiles\nExec=/usr/bin/glide-bin --ProfileManager\n'
        )
        source.write_text(native)
        setup.glide_desktop(True)
        self.assertFalse(self.data.exists())
        setup.glide_desktop(False)
        target = self.data / "applications" / source.name
        entry = self.entry(target)
        self.assertEqual("new-window;new-private-window;profile-manager;", entry["Desktop Entry"]["Actions"])
        for section, suffix in (("Desktop Entry", " %u"), ("Desktop Action new-window", " --new-window %u"),
                                ("Desktop Action new-private-window", " --private-window %u"),
                                ("Desktop Action profile-manager", " --ProfileManager")):
            self.assertEqual(setup.desktop_exec_argument(str(self.bin / "glide-bin")) + suffix, entry[section]["Exec"])
        self.assertEqual(native, source.read_text())
        source.write_text(native.replace("Name=Glide", "Name=Updated Glide"))
        setup.glide_desktop(False)
        self.assertEqual("Updated Glide", self.entry(target)["Desktop Entry"]["Name"])

    def test_onepassword_preserves_enabled_autostart_but_does_not_enable_it(self):
        source = self.system / "com.onepassword.OnePassword.desktop"
        native = "[Desktop Entry]\nName=1Password\nType=Application\nExec=/opt/1Password/1password %U\nDBusActivatable=true\n"
        source.write_text(native)
        setup.onepassword_desktop(False)
        autostart = self.config / "autostart" / source.name
        self.assertFalse(autostart.exists())
        autostart.parent.mkdir(parents=True)
        autostart.write_text(native.replace("%U", "--silent") + "X-GNOME-Autostart-Delay=5\n")
        setup.onepassword_desktop(False)
        setup.onepassword_desktop(False)
        entry = self.entry(autostart)["Desktop Entry"]
        self.assertEqual(setup.desktop_exec_argument(str(self.bin / "1password")) + " --silent", entry["Exec"])
        self.assertEqual("5", entry["X-GNOME-Autostart-Delay"])
        self.assertEqual("false", entry["DBusActivatable"])
        self.assertEqual(native, source.read_text())

    def test_unknown_local_commands_are_not_silently_replaced(self):
        source = self.system / "com.onepassword.OnePassword.desktop"
        source.write_text("[Desktop Entry]\nExec=/opt/1Password/1password %U\n")
        target = self.data / "applications" / source.name
        target.parent.mkdir(parents=True)
        original = "[Desktop Entry]\nExec=/custom/launcher %U\n"
        target.write_text(original)
        with self.assertRaisesRegex(RuntimeError, "unmanaged"):
            setup.onepassword_desktop(False)
        self.assertEqual(original, target.read_text())

    @unittest.skipUnless(shutil.which("gio"), "GIO is required for native desktop-entry consumption")
    def test_gio_delivers_urls_to_both_wrappers_with_spaces_in_checkout_path(self):
        for app, name, native, target_uri in (
            ("glide-bin", "glide-browser-bin.desktop", "/usr/bin/glide-bin %u", "https://example.invalid/a?b=1&c=2"),
            ("1password", "com.onepassword.OnePassword.desktop", "/opt/1Password/1password %U", "onepassword://open?vault=fixture"),
        ):
            with self.subTest(app=app):
                source = self.system / name
                source.write_text(f"[Desktop Entry]\nName=Fixture\nType=Application\nExec={native}\n")
                if app == "glide-bin":
                    setup.glide_desktop(False)
                else:
                    setup.onepassword_desktop(False)
                log = self.root / f"{app}.json"
                environment = dict(os.environ, XDG_OPEN_TEST_LOG=str(log),
                                   DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent-fixture-bus")
                result = subprocess.run(["gio", "launch", str(self.data / "applications" / name), target_uri],
                                        env=environment, text=True, capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                deadline = time.monotonic() + 3
                while not log.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(log.exists(), result.stdout + result.stderr)
                self.assertEqual([str(self.bin / app), target_uri], json.loads(log.read_text()))


if __name__ == "__main__":
    unittest.main()
