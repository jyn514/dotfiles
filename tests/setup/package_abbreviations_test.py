from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("fish"), "Fish is unavailable")
class PackageAbbreviationTests(unittest.TestCase):
    def test_shared_abbreviations_execute_repository_package_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binaries = home / "bin"
            binaries.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            (home / ".local/config").mkdir(parents=True)
            executable = home / "package executable"
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
            data = home / "package data"
            data.touch()
            (binaries / "dpkg").symlink_to(ROOT / "tests/setup/fixtures/package_query.sh")
            environment = {
                "HOME": str(home), "PATH": f"{binaries}:{ROOT / 'bin'}:/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "TERM": "dumb", "FISH_UNIT_TESTS_RUNNING": "1",
                "SSH_AUTH_SOCK": str(home / "absent-agent"),
                "PROFILE_FISH": str(ROOT / "config/config.fish"),
                "PROFILE_TEST_BIN": str(binaries),
                "PROFILE_TEST_PACKAGE_DATA": str(data),
                "PROFILE_TEST_PACKAGE_EXECUTABLE": str(executable),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            for abbreviation, command, expected in (
                ("belongs", "what-belongs", [str(data), str(executable)]),
                ("runs", "what-runs", [str(executable)]),
            ):
                with self.subTest(abbreviation=abbreviation):
                    result = subprocess.run(
                        [shutil.which("fish"), "--no-config", "-i",
                         str(ROOT / "tests/setup/fixtures/package_abbreviations.fish"),
                         abbreviation, "package with spaces"],
                        cwd=home, env=environment, text=True,
                        capture_output=True, check=False, timeout=30,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        ["file", str(ROOT / "bin" / command), *expected],
                        result.stdout.splitlines(),
                    )


if __name__ == "__main__":
    unittest.main()
