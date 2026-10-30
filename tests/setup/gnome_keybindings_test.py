"""Protect the custom-shortcut registry across native dconf export and restore."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "dev/dump-gnome-keybindings"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MEDIA = "/org/gnome/settings-daemon/plugins/media-keys/"
SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
DUMPS = (
    MEDIA + "custom-keybindings/",
    "/org/gnome/desktop/wm/keybindings/",
    "/org/gnome/shell/keybindings/",
    "/org/gnome/shell/extensions/pop-shell/",
    "/desktop/ibus/panel/emoji/",
)


class ExportFailureTests(unittest.TestCase):
    def test_failed_native_generation_never_publishes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / "dconf"
            shutil.copyfile(FIXTURES / "gnome-keybindings-fake-command.sh", command)
            command.chmod(0o755)
            for operation in ("read:" + MEDIA + "custom-keybindings", *(
                "dump:" + path for path in DUMPS
            )):
                with self.subTest(operation=operation):
                    result = subprocess.run(
                        [str(EXPORTER)], text=True, capture_output=True,
                        env={**os.environ, "PATH": directory + ":" + os.environ["PATH"],
                             "FAIL_OPERATION": operation},
                    )
                    self.assertEqual(23, result.returncode, result.stderr)
                    self.assertEqual("", result.stdout)
                    self.assertIn("injected-dconf-failure", result.stderr)

    def test_failed_transformation_never_publishes_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("dconf", "sed"):
                command = Path(directory) / name
                shutil.copyfile(FIXTURES / "gnome-keybindings-fake-command.sh", command)
                command.chmod(0o755)
            result = subprocess.run(
                [str(EXPORTER)], text=True, capture_output=True,
                env={**os.environ, "PATH": directory + ":" + os.environ["PATH"],
                     "FAIL_OPERATION": ""},
            )
            self.assertEqual(24, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertIn("injected-sed-failure", result.stderr)


class NativeRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for tool in ("dconf", "gsettings", "dbus-run-session"):
            if shutil.which(tool) is None:
                raise unittest.SkipTest(f"optional native GNOME test requires {tool}")
        schemas = subprocess.run(
            ["gsettings", "list-schemas"], text=True, capture_output=True, check=True,
        )
        if SCHEMA not in schemas.stdout.splitlines():
            raise unittest.SkipTest("optional native GNOME media-keys schema is not installed")

    def test_exact_registry_roundtrips_without_unrelated_parent_preferences(self):
        subset = f"['{MEDIA}custom-keybindings/custom4/', '{MEDIA}custom-keybindings/custom0/']"
        for selection in (subset, "@as []", None):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                env = dict(os.environ)
                for key in ("DBUS_SESSION_BUS_ADDRESS", "DBUS_STARTER_ADDRESS",
                            "DBUS_STARTER_BUS_TYPE", "GSETTINGS_SCHEMA_DIR"):
                    env.pop(key, None)
                env.update(HOME=directory, GSETTINGS_BACKEND="dconf")
                for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                            "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
                    path = home / key
                    path.mkdir(mode=0o700)
                    env[key] = str(path)
                source = home / "source.profile"
                source.write_text("user-db:source\n")
                restore = home / "restore.profile"
                restore.write_text("user-db:restore\n")
                env["DCONF_PROFILE"] = str(source)
                exported = self.run_bus(
                    env, "gnome-keybindings-export.sh", str(ROOT), selection or "",
                )
                self.assertNotIn("not-exported", exported)
                registry_line = "custom-keybindings="
                if selection is None:
                    self.assertNotIn(registry_line, exported)
                else:
                    self.assertIn(registry_line + selection, exported)
                snapshot = home / "snapshot.ini"
                snapshot.write_text(exported)
                env["DCONF_PROFILE"] = str(restore)
                restored = self.run_bus(env, "gnome-keybindings-inspect.sh", str(snapshot))
                original = self.run_bus(
                    {**env, "DCONF_PROFILE": str(source)}, "gnome-keybindings-inspect.sh",
                )
                self.assertEqual(original, restored)
                self.assertEqual(selection or "@as []", restored.splitlines()[0])

    def run_bus(self, env, fixture, *arguments):
        result = subprocess.run(
            ["dbus-run-session", "--", "sh", str(FIXTURES / fixture), *arguments],
            env=env, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout


if __name__ == "__main__":
    unittest.main()
