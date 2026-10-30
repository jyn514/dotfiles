from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class MkcdAbbreviationTests(unittest.TestCase):
    def test_registered_expansion_creates_all_paths_and_changes_directory_only_on_success(self) -> None:
        for shell in ("bash", "fish"):
            executable = shutil.which(shell)
            if not executable:
                self.skipTest(f"{shell} is unavailable")
            for case in ("nested", "multiple", "mkdir_failure"):
                with self.subTest(shell=shell, case=case), tempfile.TemporaryDirectory() as directory:
                    home = Path(directory)
                    (home / ".profile").symlink_to(ROOT / "config/profile")
                    (home / ".local/config").mkdir(parents=True)
                    paths = ["directory with space/child"]
                    if case == "multiple":
                        paths.append("another directory/child")
                    elif case == "mkdir_failure":
                        (home / "blocker").touch()
                        paths.append("blocker/child")
                    environment = {
                        "HOME": str(home), "PATH": f"{ROOT / 'bin'}:/usr/bin:/bin",
                        "XDG_CONFIG_HOME": str(home / ".config"),
                        "XDG_DATA_HOME": str(home / ".local/share"),
                        "XDG_CACHE_HOME": str(home / ".cache"),
                        "TERM": "dumb", "FISH_UNIT_TESTS_RUNNING": "1",
                        "SSH_AUTH_SOCK": str(home / "absent-agent"),
                        "PROFILE_FISH": str(ROOT / "config/config.fish"),
                        "BASH_PROFILE_READ": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    }
                    if shell == "fish":
                        command = [executable, "--no-config", "-i",
                                   str(ROOT / "tests/setup/fixtures/mkcd_abbreviation.fish"), *paths]
                    else:
                        command = [executable, "--noprofile", "--norc", "-i",
                                   str(ROOT / "tests/setup/fixtures/profile_command.sh"),
                                   'mkdc "$@"; result=$?; printf "%s\\n%s\\n" "$result" "$PWD"',
                                   *paths]
                    result = subprocess.run(command, cwd=home, env=environment,
                                            text=True, capture_output=True, check=False, timeout=30)
                    self.assertEqual(0, result.returncode, result.stderr)
                    lines = result.stdout.splitlines()
                    self.assertEqual(2, len(lines), result.stdout + result.stderr)
                    execution_status = int(lines[0])
                    expected_directory = home if case == "mkdir_failure" else home / paths[0]
                    self.assertEqual(str(expected_directory), lines[1], result.stderr)
                    # Even when a later operand fails, mkdir attempts the earlier one.
                    self.assertTrue((home / paths[0]).is_dir(), result.stderr)
                    if case == "mkdir_failure":
                        self.assertNotEqual(0, execution_status, result.stderr)
                    else:
                        self.assertEqual(0, execution_status, result.stderr)
                        for path in paths:
                            self.assertTrue((home / path).is_dir(), result.stderr)


if __name__ == "__main__":
    unittest.main()
