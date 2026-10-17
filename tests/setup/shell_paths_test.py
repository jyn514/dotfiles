"""Exercise shell path arguments through the real helpers, without host effects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/setup/fixtures"


class ShellPathsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.root / "home with spaces [ab]"
        (self.home / ".local/bin").mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.environment = os.environ | {
            "HOME": str(self.home),
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
        }

    def run_helper(self, operation, library, *arguments, **environment):
        return subprocess.run(
            ["sh", FIXTURES / "shell_path_entrypoint.sh", operation, ROOT / library, *arguments],
            cwd=self.root, env=self.environment | environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
        )

    def test_alias_preserves_command_names_with_spaces_and_glob_characters(self):
        for name in ("a tool", "tool[ab]"):
            with self.subTest(name=name):
                source = self.bin / name
                source.symlink_to(shutil.which("true"))
                # If expanded as a glob, the source name can select this different executable.
                if name == "tool[ab]":
                    (self.bin / "toola").symlink_to(shutil.which("false"))
                    (self.root / "toola").touch()
                target_name = "alias " + name
                result = self.run_helper("alias", "lib/shell/lib.sh", target_name, name)
                self.assertEqual(0, result.returncode, result.stderr)
                target = self.home / ".local/bin" / target_name
                self.assertTrue(target.is_symlink())
                self.assertEqual(source, target.readlink())

    def test_alias_leaves_an_existing_executable_alone(self):
        source = self.bin / "source"
        source.symlink_to(shutil.which("true"))
        target = self.home / ".local/bin/existing"
        target.symlink_to(shutil.which("false"))
        before = target.readlink()
        result = self.run_helper("alias", "lib/shell/lib.sh", "existing", "source")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, target.readlink())

    def test_alias_does_not_create_a_link_for_a_missing_command(self):
        result = self.run_helper("alias", "lib/shell/lib.sh", "alias", "missing-fixture-command")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.home / ".local/bin/alias").exists())

    def test_sandbox_profile_paths_follow_home_without_splitting(self):
        result = self.run_helper("profile", "tools/codex-sandbox/image/dotfiles-profile.sh")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [str(self.home / suffix) for suffix in (
                ".config", ".local/lib/cargo", ".local/lib/rustup", ".local/lib/go",
                ".local/lib/go/bin", ".cache/cargo",
            )],
            result.stdout.rstrip("\0").split("\0"),
        )

    def test_pam_unlock_preserves_home_and_only_unlocks_a_locked_home(self):
        binary = self.bin / "fscrypt"
        subprocess.run(["cp", FIXTURES / "pam_fscrypt.py", binary], check=True)
        subprocess.run(["cmp", FIXTURES / "pam_fscrypt.py", binary], check=True)
        binary.chmod(0o755)
        log = self.root / "fscrypt.jsonl"
        for locked in (False, True):
            with self.subTest(locked=locked):
                log.write_text("")
                result = self.run_helper(
                    "pam", "lib/02-pam-unlock.sh", FSCRYPT_LOG=str(log),
                    FSCRYPT_LOCKED="1" if locked else "0",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                expected = [["status", str(self.home)]]
                if locked:
                    expected.append(["unlock", str(self.home)])
                self.assertEqual(expected, [json.loads(line) for line in log.read_text().splitlines()])


if __name__ == "__main__":
    unittest.main()
