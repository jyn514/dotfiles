"""Exercise portable preparation and native moves only in disposable directories."""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
import prepare_desktop as setup
sys.path.pop(0)
desktop = setup.desktop


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="prepare browser's [fixture] ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        current = pwd.getpwuid(os.getuid())
        self.home = self.root / "home"
        self.home.mkdir()
        self.account = pwd.struct_passwd((current.pw_name, "x", os.getuid(), os.getgid(), "", str(self.home), current.pw_shell))
        self.registry = self.home / ".config/glide/glide"
        self.storage = self.root / "private"
        self.stage = self.root / "stage"
        self.stage.mkdir()

    def registry_with_profiles(self):
        self.registry.mkdir(parents=True)
        for name in ("profile-a", "profile-b"):
            (self.registry / name).mkdir()
            (self.registry / name / "cookies.sqlite").write_bytes((name + " opaque fixture data").encode())
        (self.registry / "profiles.ini").write_text(
            "[General]\nStartWithLastProfile=1\n[Profile0]\nName=First\nIsRelative=1\nPath=profile-a\n"
            "[Profile1]\nName=Second\nIsRelative=1\nPath=profile-b\n[Installfixture]\nDefault=profile-a\nLocked=1\n"
        )
        (self.registry / "installs.ini").write_text("[fixture]\nDefault=profile-a\nLocked=1\n")

    def execute_migration(self, steps):
        # Root ownership/traversal is covered by the installed runtime acceptance.
        # These exact native commands operate on owned temporary trees as self.
        self.storage.mkdir(mode=0o710)
        for step in steps:
            result = subprocess.run(step.argv, text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_move_preserves_all_profile_bytes_and_registry_identity(self):
        self.registry_with_profiles()
        before = {str(path.relative_to(self.registry)): (path.stat().st_ino, path.read_bytes())
                  for path in self.registry.rglob("*") if path.is_file()}
        steps, description = setup.profile_steps(self.account, self.stage, self.storage)
        self.assertIn("whole native profile tree", description)
        self.execute_migration(steps)
        self.assertTrue(self.registry.is_symlink())
        after = {str(path.relative_to(self.registry)): (path.stat().st_ino, path.read_bytes())
                 for path in self.registry.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        desktop.check_registered_profiles(self.registry, self.storage / "profiles")

    def test_external_profiles_and_unexpected_registry_links_are_refused(self):
        self.registry_with_profiles()
        external = self.root / "external-profile"
        external.mkdir()
        with (self.registry / "profiles.ini").open("a") as output:
            output.write(f"[Profile2]\nName=External\nIsRelative=0\nPath={external}\n")
        with self.assertRaisesRegex(ValueError, "outside protected storage"):
            setup.profile_steps(self.account, self.stage, self.storage)
        self.assertFalse(self.storage.exists())
        self.assertFalse(self.registry.is_symlink())
        physical = self.root / "physical-registry"
        self.registry.rename(physical)
        self.registry.symlink_to(physical)
        with self.assertRaisesRegex(ValueError, "unexpected registry symlink"):
            setup.profile_steps(self.account, self.stage, self.storage)
        self.assertTrue(physical.is_dir())

    def test_changed_registry_stops_before_moving_any_profile(self):
        self.registry_with_profiles()
        steps, _ = setup.profile_steps(self.account, self.stage, self.storage)
        with (self.registry / "profiles.ini").open("a") as output:
            output.write("\n[Profile2]\nName=New\nPath=new\nIsRelative=1\n")
        self.storage.mkdir()
        for step in steps:
            result = subprocess.run(step.argv, text=True, capture_output=True)
            if result.returncode:
                break
        else:
            self.fail("stale registry was accepted")
        self.assertTrue(self.registry.is_dir())
        self.assertFalse(self.registry.is_symlink())
        self.assertFalse((self.storage / "profiles").exists())

    def test_newly_created_registry_files_stop_before_moving_profiles(self):
        for name, dangling in (("profiles.ini", False), ("installs.ini", False), ("installs.ini", True)):
            with self.subTest(name=name, dangling=dangling), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home = root / "home"
                registry = home / ".config/glide/glide"
                registry.mkdir(parents=True)
                stage = root / "stage"
                stage.mkdir()
                storage = root / "protected"
                account = pwd.struct_passwd((self.account.pw_name, "x", os.getuid(), os.getgid(), "", str(home), self.account.pw_shell))
                steps, _ = setup.profile_steps(account, stage, storage)
                if dangling:
                    (registry / name).symlink_to(root / "absent-target")
                else:
                    (registry / name).write_text("[unexpected]\nDefault=/outside\n")
                storage.mkdir()
                for step in steps:
                    result = subprocess.run(step.argv, text=True, capture_output=True)
                    if result.returncode:
                        break
                else:
                    self.fail("new registry file was accepted")
                self.assertFalse(registry.is_symlink())
                self.assertFalse((storage / "profiles").exists())

    def test_new_install_has_empty_protected_registry_ready_for_native_initialization(self):
        steps, description = setup.profile_steps(self.account, self.stage, self.storage)
        self.assertIn("fresh", description)
        self.execute_migration(steps)
        self.assertEqual(self.storage / "profiles", self.registry.resolve())
        desktop.check_registered_profiles(self.registry, self.storage / "profiles")
        (self.registry / "unexpected-file").touch()
        with self.assertRaises(FileNotFoundError):
            desktop.check_registered_profiles(self.registry, self.storage / "profiles")

    def test_existing_empty_registry_can_move_without_synthetic_profile_names(self):
        self.registry.mkdir(parents=True)
        steps, _ = setup.profile_steps(self.account, self.stage, self.storage)
        self.execute_migration(steps)
        desktop.check_registered_profiles(self.registry, self.storage / "profiles")

    def test_unmanaged_storage_is_not_overwritten_or_deleted(self):
        self.registry_with_profiles()
        self.storage.mkdir()
        (self.storage / "retain-me").write_text("unrelated")
        with self.assertRaisesRegex(ValueError, "partial installation"):
            setup.profile_steps(self.account, self.stage, self.storage)
        self.assertEqual("unrelated", (self.storage / "retain-me").read_text())

    def test_update_of_managed_storage_emits_no_profile_moves(self):
        self.storage.mkdir(mode=0o710)
        self.registry.parent.mkdir(parents=True)
        self.registry.symlink_to(self.storage / "profiles")
        original_stat = Path.stat
        def metadata(path, *args, **kwargs):
            value = original_stat(path, *args, **kwargs)
            if path == self.storage and kwargs.get("follow_symlinks", True):
                fields = list(value)
                fields[4] = 0
                fields[5] = os.getgid()
                return os.stat_result(fields)
            return value
        with patch.object(Path, "stat", metadata), patch.object(setup.grp, "getgrnam", return_value=type("Group", (), {"gr_gid": os.getgid()})()):
            steps, description = setup.profile_steps(self.account, self.stage, self.storage)
        self.assertEqual([], steps)
        self.assertIn("stay in place", description)

    def test_prepared_install_uses_snapshots_and_account_derived_units(self):
        loader = self.root / "guard-loader"
        loader.write_bytes(b"guard snapshot fixture")
        account = pwd.struct_passwd(("fixture", "x", 4321, 8765, "", str(self.home), "/bin/fish"))
        with patch.object(setup.shutil, "which", return_value=None):
            commands, _ = setup.prepare(account, self.stage, loader, self.storage)
        loader.write_bytes(b"changed after preparation")
        self.assertEqual(b"guard snapshot fixture", (self.stage / "proc-read-guard").read_bytes())
        content = commands.read_text()
        self.assertIn("/usr/bin/sudo -u root -- /usr/bin/install", content)
        self.assertNotIn("usermod", content)
        self.assertNotIn("useradd", content)
        self.assertNotIn("'rm'", content)
        service = (self.stage / "private-desktop-4321-glide@.service").read_text()
        self.assertIn("User=4321\nGroup=8765\n", service)
        self.assertNotIn("1000", service)
        self.assertIn(setup.fish_quote(self.stage / "desktop.py"), content)
        self.assertNotIn("/var/lib/browser", content)

    def test_setup_command_dispatches_without_privilege_or_profile_mutation(self):
        binaries = self.root / "bin"
        binaries.mkdir()
        recorder = setup.ROOT / "tests/setup/fixtures/record_private_desktop_setup.py"
        (binaries / "python3").symlink_to(recorder)
        log = self.root / "dispatch.json"
        env = dict(os.environ, HOME=str(self.home), PATH=f"{binaries}:{os.defpath}",
                   PRIVATE_DESKTOP_SETUP_LOG=str(log), SETUP_NONINTERACTIVE="1")
        for option in ("private-desktop", "13"):
            with self.subTest(option=option):
                result = subprocess.run(["sh", str(setup.ROOT / "setup"), option], env=env,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(["tools/proc-hardening/prepare_desktop.py"], json.loads(log.read_text()))
        self.assertFalse(self.registry.exists())

    def test_preflight_checks_both_current_and_persistent_groups(self):
        groups = {"browser": type("Group", (), {"gr_gid": 12345})(),
                  "onepassword": type("Group", (), {"gr_gid": 23456})()}
        for current, persistent, allowed in (([], [], True), ([12345], [], False), ([], [23456], False)):
            with self.subTest(current=current, persistent=persistent), \
                 patch.object(setup.os, "geteuid", return_value=1000), \
                 patch.object(setup.os, "access", return_value=True), \
                 patch.object(setup.os, "getgroups", return_value=current), \
                 patch.object(setup.os, "getgrouplist", return_value=persistent), \
                 patch.object(setup.grp, "getgrnam", side_effect=groups.__getitem__):
                if allowed:
                    setup.preflight(self.account)
                else:
                    with self.assertRaisesRegex(ValueError, "ordinary login"):
                        setup.preflight(self.account)

    @unittest.skipUnless(shutil.which("fish"), "Fish is needed for native command-block parsing")
    def test_fish_argument_roundtrip_and_failure_stops_later_commands(self):
        values = ["space here", "quote'and\"", "\\slash", "$variable", "[glob]*", "☃", "line\nbreak"]
        output = self.root / "arguments"
        script = setup.render_steps([setup.Step(("/usr/bin/printf", "%s\\n", *values), root=False)])
        result = subprocess.run(["fish", "-c", script], text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("\n".join(values) + "\n", result.stdout)
        failed = setup.render_steps([setup.Step(("/usr/bin/false",), root=False),
                                     setup.Step(("/usr/bin/touch", str(output)), root=False)])
        result = subprocess.run(["fish", "-c", failed], text=True, capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
