#!/usr/bin/env python3

import os
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TrackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=ROOT)
        self.fixture = Path(self.tempdir.name) / "repo"
        self.fixture.mkdir()
        shutil.copy2(ROOT / "track", self.fixture / "track")
        for directory in ("bin", "config", "global", "install", "lib", "libexec", "libexec/setup"):
            (self.fixture / directory).mkdir()
        shutil.copy2(ROOT / "install.conf.json", self.fixture / "install.conf.json")
        shutil.copy2(ROOT / "libexec/track_file.py", self.fixture / "libexec/track_file.py")
        (self.fixture / "install/global.txt").write_text("")
        (self.fixture / "libexec/setup/setup_sudo.sh").write_text("#!/bin/sh\nexit 99\n")

        self.home = Path(self.tempdir.name) / "home"
        self.home.mkdir()
        self.fake_bin = Path(self.tempdir.name) / "fake-bin"
        self.fake_bin.mkdir()
        sudo = self.fake_bin / "sudo"
        sudo.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" > "$TRACK_SUDO_LOG"\n'
            '[ ! -e "$TRACK_SUDO_FAIL_FILE" ]\n'
        )
        sudo.chmod(0o755)
        self.sudo_log = Path(self.tempdir.name) / "sudo.log"
        self.sudo_fail = Path(self.tempdir.name) / "sudo.fail"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_track(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            HOME=str(self.home),
            PATH=f"{self.fake_bin}:{env['PATH']}",
            TRACK_SUDO_LOG=str(self.sudo_log),
            TRACK_SUDO_FAIL_FILE=str(self.sudo_fail),
        )
        return subprocess.run(
            ["sh", str(self.fixture / "track"), *arguments],
            cwd=self.fixture,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def links(self) -> dict[str, object]:
        config = json.loads((self.fixture / "install.conf.json").read_text())
        return next(directive["link"] for directive in config if "link" in directive)

    def test_tracks_home_file_by_moving_it_and_linking_it_back(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")

        result = self.run_track(str(source))

        self.assertEqual(0, result.returncode, result.stderr)
        tracked = self.fixture / "config/example"
        self.assertEqual("configuration\n", tracked.read_text())
        self.assertTrue(source.is_symlink())
        self.assertEqual(tracked.resolve(), source.resolve())
        self.assertEqual("config/example", self.links()["$HOME/.example"])

    def test_optional_name_controls_the_tracked_basename(self) -> None:
        source = self.home / ".config/tool/settings"
        source.parent.mkdir(parents=True)
        source.write_text("configuration\n")

        result = self.run_track(str(source), "tool.conf")

        self.assertEqual(0, result.returncode, result.stderr)
        tracked = self.fixture / "config/tool.conf"
        self.assertEqual("configuration\n", tracked.read_text())
        self.assertEqual(
            "config/tool.conf",
            self.links()["$HOME/.config/tool/settings"],
        )

    def test_untracks_home_file_by_restoring_it_and_removing_link_entry(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")
        self.assertEqual(0, self.run_track(str(source)).returncode)

        result = self.run_track("--untrack", str(source))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(source.is_symlink())
        self.assertEqual("configuration\n", source.read_text())
        self.assertFalse((self.fixture / "config/example").exists())
        self.assertNotIn("$HOME/.example", self.links())

    def test_untracks_home_directory(self) -> None:
        source = self.home / ".example"
        source.mkdir()
        (source / "settings").write_text("configuration\n")
        self.assertEqual(0, self.run_track(str(source)).returncode)

        result = self.run_track("--untrack", str(source))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(source.is_symlink())
        self.assertEqual("configuration\n", (source / "settings").read_text())
        self.assertFalse((self.fixture / "config/example").exists())

    def test_untrack_dry_run_does_not_modify_files_or_manifest(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")
        self.assertEqual(0, self.run_track(str(source)).returncode)
        original_config = (self.fixture / "install.conf.json").read_text()

        result = self.run_track("--dry-run", "--untrack", str(source))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(source.is_symlink())
        self.assertEqual(original_config, (self.fixture / "install.conf.json").read_text())
        self.assertIn("remove $HOME/.example", result.stdout)

    def test_untrack_rejects_a_destination_that_is_not_the_tracked_symlink(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")
        config = json.loads((self.fixture / "install.conf.json").read_text())
        links = next(directive["link"] for directive in config if "link" in directive)
        links["$HOME/.example"] = "config/example"
        (self.fixture / "install.conf.json").write_text(json.dumps(config, indent=2) + "\n")
        (self.fixture / "config/example").write_text("tracked configuration\n")

        result = self.run_track("--untrack", str(source))

        self.assertEqual(1, result.returncode)
        self.assertIn("not the expected symlink", result.stderr)
        self.assertEqual("configuration\n", source.read_text())
        self.assertEqual("tracked configuration\n", (self.fixture / "config/example").read_text())

    def test_tracks_system_file_by_copying_it_and_applying_globals(self) -> None:
        source = Path(self.tempdir.name) / "system.conf"
        source.write_text("system configuration\n")

        result = self.run_track(str(source))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("system configuration\n", source.read_text())
        self.assertEqual(
            "system configuration\n",
            (self.fixture / "global/system.conf").read_text(),
        )
        self.assertEqual(
            f"system.conf={source}\n",
            (self.fixture / "install/global.txt").read_text(),
        )
        self.assertEqual(
            "libexec/setup/setup_sudo.sh copy_globals --force\n",
            self.sudo_log.read_text(),
        )

    def test_rejects_missing_or_extra_arguments(self) -> None:
        missing = self.run_track()
        extra = self.run_track("one", "two", "three")

        self.assertEqual(2, missing.returncode)
        self.assertIn("usage:", missing.stderr)
        self.assertEqual(2, extra.returncode)
        self.assertIn("usage:", extra.stderr)

    def test_dry_run_does_not_move_or_modify_home_file(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")
        original_config = (self.fixture / "install.conf.json").read_text()

        result = self.run_track("--dry-run", str(source))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("configuration\n", source.read_text())
        self.assertFalse((self.fixture / "config/example").exists())
        self.assertEqual(original_config, (self.fixture / "install.conf.json").read_text())
        self.assertIn("move", result.stdout)

    def test_rejects_duplicate_destination_before_moving_file(self) -> None:
        source = self.home / ".bashrc"
        source.write_text("local bashrc\n")

        result = self.run_track(str(source))

        self.assertEqual(1, result.returncode)
        self.assertIn("already tracked", result.stderr)
        self.assertEqual("local bashrc\n", source.read_text())

    def test_global_failure_rolls_back_manifest_and_copy(self) -> None:
        source = Path(self.tempdir.name) / "system.conf"
        source.write_text("system configuration\n")
        self.sudo_fail.touch()

        result = self.run_track(str(source))

        self.assertEqual(1, result.returncode)
        self.assertEqual("", (self.fixture / "install/global.txt").read_text())
        self.assertFalse((self.fixture / "global/system.conf").exists())
        self.assertEqual("system configuration\n", source.read_text())

    def test_manifest_write_failure_restores_home_file(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")
        implementation = self.fixture / "libexec/track_file.py"
        implementation.write_text(
            implementation.read_text().replace(
                "        atomic_write(config_path, new_config)\n",
                '        raise OSError("simulated manifest write failure")\n',
                1,
            )
        )

        result = self.run_track(str(source))

        self.assertEqual(1, result.returncode)
        self.assertFalse(source.is_symlink())
        self.assertEqual("configuration\n", source.read_text())
        self.assertFalse((self.fixture / "config/example").exists())

    def test_untrack_manifest_failure_restores_symlink_and_tracked_file(self) -> None:
        source = self.home / ".example"
        source.write_text("configuration\n")
        self.assertEqual(0, self.run_track(str(source)).returncode)
        original_config = (self.fixture / "install.conf.json").read_text()
        implementation = self.fixture / "libexec/track_file.py"
        implementation.write_text(
            implementation.read_text().replace(
                "        tracked.rename(source)\n        atomic_write(config_path, new_config)\n",
                "        tracked.rename(source)\n"
                '        raise OSError("simulated manifest write failure")\n',
                1,
            )
        )

        result = self.run_track("--untrack", str(source))

        self.assertEqual(1, result.returncode)
        self.assertTrue(source.is_symlink())
        self.assertEqual("configuration\n", source.read_text())
        self.assertEqual("configuration\n", (self.fixture / "config/example").read_text())
        self.assertEqual(original_config, (self.fixture / "install.conf.json").read_text())


if __name__ == "__main__":
    unittest.main()
