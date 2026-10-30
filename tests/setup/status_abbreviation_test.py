import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class StatusAbbreviationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="status-abbreviation-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.home = self.base / "home"
        self.home.mkdir()
        (self.home / ".profile").symlink_to(ROOT / "config/profile")
        (self.home / ".gitconfig").symlink_to(ROOT / "config/gitconfig")
        (self.home / ".local/config").mkdir(parents=True)
        self.binaries = self.base / "bin"
        self.binaries.mkdir()
        self.case = self.base / "case"
        self.case.mkdir()
        (self.case / "directory-marker.txt").write_text("fixture only\n")
        (self.case / "subdirectory").mkdir()
        self.environment = {
            "HOME": str(self.home), "PATH": f"{ROOT / 'bin'}:/usr/bin:/bin",
            "DOTFILES": str(ROOT),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "TERM": "dumb", "FISH_UNIT_TESTS_RUNNING": "1",
            "SSH_AUTH_SOCK": str(self.home / "absent-agent"),
            "PROFILE_FISH": str(ROOT / "config/config.fish"),
            "PROFILE_TEST_BIN": str(self.binaries),
            "BASH_PROFILE_READ": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CEILING_DIRECTORIES": str(self.base),
            "JJ_CONFIG": "", "NO_COLOR": "1",
        }

    def git_repository(self) -> None:
        for arguments in (("init", "--quiet"), ("config", "alias.s", "status --short")):
            result = self.run_command(["/usr/bin/git", *arguments])
            self.assertEqual(0, result.returncode, result.stderr)

    def run_command(self, command, **kwargs):
        return subprocess.run(command, cwd=self.case, env=self.environment,
                              text=True, capture_output=True, timeout=30, **kwargs)

    def provider(self, name: str, body: str) -> None:
        executable = self.binaries / name
        executable.write_text("#!/bin/sh\n" + body)
        executable.chmod(0o755)

    def native_jj(self) -> str:
        executable = os.environ.get("DOTFILES_TEST_JJ_REAL") or shutil.which("jj")
        if not executable:
            self.skipTest("native JJ is unavailable")
        return executable

    def consumer(self, shell: str):
        executable = shutil.which(shell)
        if not executable:
            self.skipTest(f"{shell} is unavailable")
        if shell == "fish":
            command = [executable, "--no-config", "-i", str(FIXTURES / "status_abbreviation.fish")]
        else:
            command = [executable, "--noprofile", "--norc", "-i",
                       str(FIXTURES / "profile_command.sh"),
                       "alias s; printf 'consumer_begin\\n'; s; result=$?; "
                       "printf 'consumer_end=%s\\n' \"$result\"; "
                       "printf 'reference_begin\\n'; status; result=$?; "
                       "printf 'reference_end=%s\\n' \"$result\""]
        result = self.run_command(command)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("job control", result.stdout)
        self.assertNotIn("login shell", result.stdout)
        before, rest = result.stdout.split("consumer_begin\n", 1)
        output, after = rest.split("consumer_end=", 1)
        status, tail = after.split("\n", 1)
        self.assertEqual("0", status, result.stdout + result.stderr)
        # Exactly one registration line before execution also proves startup
        # did not accidentally run the sourced show-status helper.
        self.assertEqual(1, len(before.splitlines()), result.stdout)
        if shell == "fish":
            self.assertEqual("expansion=show-status --run\n", before)
            self.assertEqual("status_type=builtin\nbuiltin_status_available\n", tail)
        else:
            reference = tail.removeprefix("reference_begin\n").removesuffix("reference_end=0\n")
            self.assertEqual(output, reference, result.stdout)
        return output

    def assert_consumers(self, *expected: str) -> None:
        outputs = []
        for shell in ("bash", "fish"):
            with self.subTest(shell=shell):
                output = self.consumer(shell)
                for text in expected:
                    self.assertIn(text, output)
                outputs.append(output)
        if len(outputs) == 2:
            self.assertEqual(outputs[0], outputs[1])

    def test_registered_status_lists_nonrepository_directory(self) -> None:
        self.assert_consumers("directory-marker.txt", "subdirectory/")

    def test_registered_status_uses_native_git_alias(self) -> None:
        self.git_repository()
        self.assert_consumers("?? directory-marker.txt")

    def test_registered_status_uses_native_jj(self) -> None:
        jj = self.native_jj()
        (self.binaries / "jj").symlink_to(jj)
        result = self.run_command([jj, "git", "init", "."])
        self.assertEqual(0, result.returncode, result.stderr)
        # The consumer deliberately ignores working-copy snapshots. Establish
        # a real recorded change first, as an already active workspace would.
        result = self.run_command([jj, "status"])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assert_consumers("Working copy changes:", "directory-marker.txt", "Working copy")

    def test_jj_failure_falls_back_to_git(self) -> None:
        self.provider("jj", 'case "$1" in workspace) exit 0;; status) exit 7;; esac\n')
        self.git_repository()
        self.assert_consumers("?? directory-marker.txt")

    def test_jj_timeout_falls_back_to_directory(self) -> None:
        self.provider("jj", 'case "$1" in workspace) exit 0;; status) exec sleep 2;; esac\n')
        self.assert_consumers("directory-marker.txt", "subdirectory/")

    def test_git_failure_is_not_reported_as_success(self) -> None:
        self.provider("git", 'case "$1" in rev-parse) echo true;; s) exit 9;; *) exec /usr/bin/git "$@";; esac\n')
        for shell in ("bash", "fish"):
            with self.subTest(shell=shell):
                # Same complete loader/registered consumer, but check its raw
                # status rather than the success-only helper assertions.
                if shell == "fish":
                    command = [shutil.which(shell), "--no-config", "-i",
                               str(FIXTURES / "status_abbreviation.fish")]
                else:
                    command = [shutil.which(shell), "--noprofile", "--norc", "-i",
                               str(FIXTURES / "profile_command.sh"), "s; printf 'consumer_end=%s\\n' \"$?\""]
                result = self.run_command(command)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("consumer_end=9\n", result.stdout)

    def test_old_show_status_source_and_no_argument_contract_stays_silent(self) -> None:
        for command in (
            ["/bin/sh", str(ROOT / "bin/show-status")],
            ["/bin/sh", "-c", 'helper=$1; shift; . "$helper"; command -v status', "sh", str(ROOT / "bin/show-status")],
        ):
            with self.subTest(command=command):
                result = self.run_command(command)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("status\n" if "-c" in command else "", result.stdout)
                self.assertEqual("", result.stderr)


if __name__ == "__main__":
    unittest.main()
