"""Glide discovers 1Password's existing manifest without copying or replacing it."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "libexec/setup/glide.py"
spec = importlib.util.spec_from_file_location("glide_native_messaging_setup", SCRIPT)
glide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(glide)


class NativeMessagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.directory / "home with spaces"
        self.home.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {"HOME": str(self.home)}))
        self.enterContext(mock.patch.object(glide.sys, "platform", "linux"))
        name = "com.1password.1password.json"
        self.source = self.home / ".mozilla/native-messaging-hosts" / name
        self.destination = self.home / ".glide-browser/native-messaging-hosts" / name

    def provide_manifest(self):
        self.source.parent.mkdir(parents=True)
        self.source.write_text('{"name":"fixture connector"}\n')

    def test_missing_provider_manifest_creates_nothing(self):
        glide.configure_native_messaging()
        self.assertFalse((self.home / ".glide-browser").exists())

    def test_link_is_idempotent_and_tracks_provider_updates(self):
        self.provide_manifest()
        glide.configure_native_messaging()
        original = self.destination.lstat()
        glide.configure_native_messaging()
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(original.st_ino, self.destination.lstat().st_ino)
        self.assertEqual(self.source.resolve(), self.destination.resolve())
        replacement = self.source.with_suffix(".replacement")
        replacement.write_text('{"name":"updated connector"}\n')
        replacement.replace(self.source)
        self.assertEqual('{"name":"updated connector"}\n', self.destination.read_text())

    def test_regular_local_configuration_is_preserved(self):
        self.provide_manifest()
        self.destination.parent.mkdir(parents=True)
        self.destination.write_text("local configuration\n")
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            glide.configure_native_messaging()
        self.assertEqual("local configuration\n", self.destination.read_text())

    def test_other_links_including_dangling_ones_are_preserved(self):
        self.provide_manifest()
        self.destination.parent.mkdir(parents=True)
        other = self.directory / "missing local manifest"
        self.destination.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            glide.configure_native_messaging()
        self.assertEqual(other, self.destination.readlink())

    def test_macos_is_unchanged_even_with_a_linux_manifest_present(self):
        self.provide_manifest()
        with mock.patch.object(glide.sys, "platform", "darwin"):
            glide.configure_native_messaging()
        self.assertFalse((self.home / ".glide-browser").exists())

    def test_explicit_cli_mode_does_not_change_mise_configuration(self):
        self.provide_manifest()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "native-messaging"],
            env=os.environ, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertTrue(self.destination.is_symlink())
        self.assertFalse((self.home / ".config/mise").exists())

    def test_dotfiles_setup_installs_the_manifest_link(self):
        self.provide_manifest()
        repository = self.directory / "repository with spaces"
        repository.mkdir()
        for relative in ("setup", "libexec/setup/glide.py"):
            destination = repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", str(ROOT / relative), str(destination)], check=True)
            subprocess.run(["cmp", str(ROOT / relative), str(destination)], check=True)
        (repository / "lib").symlink_to(ROOT / "lib", target_is_directory=True)
        # Other setup steps retain their real interfaces but have no effects.
        (repository / "libexec/backup_dotfile_collisions.py").write_text("pass\n")
        dotbot = repository / "vendor/dotbot/bin/dotbot"
        dotbot.parent.mkdir(parents=True)
        dotbot.write_text("#!/bin/sh\nexit 0\n")
        dotbot.chmod(0o755)
        binaries = self.directory / "bin"
        binaries.mkdir()
        (binaries / "python3").symlink_to(sys.executable)
        (binaries / "jj").symlink_to(shutil.which("false"))
        (self.home / ".config/git").mkdir(parents=True)
        result = subprocess.run(
            ["sh", str(repository / "setup"), "dotfiles"],
            env=os.environ | {"PATH": f"{binaries}:{os.environ['PATH']}"},
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(self.source.resolve(), self.destination.resolve())


if __name__ == "__main__":
    unittest.main()
