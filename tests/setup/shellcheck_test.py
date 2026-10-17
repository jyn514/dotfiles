"""Native ShellCheck/discovery tests in an owned, non-Git fixture checkout."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/setup/fixtures"


@unittest.skipUnless(shutil.which("rg") and shutil.which("shellcheck"),
                     "ripgrep and ShellCheck required")
class ShellCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.directory)
        self.checker = self.root / "dev/check-shell.py"
        self.copy(ROOT / "dev/check-shell.py", self.checker)
        self.marker = self.root / "executed"
        self.environment = os.environ | {"SHELLCHECK_EXECUTION_MARKER": str(self.marker)}

    def copy(self, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", source, destination], check=True)
        subprocess.run(["cmp", source, destination], check=True)

    def script(self, name, *, valid=True, shebang=True):
        path = self.root / name
        self.copy(FIXTURES / ("shellcheck-valid.txt" if valid else "shellcheck-unquoted.txt"), path)
        if shebang:
            path.write_bytes(b"#!/bin/sh\n" + path.read_bytes())
        return path

    def run_check(self, **environment):
        result = subprocess.run(
            [sys.executable, self.checker], cwd=self.root.parent,
            env=self.environment | environment, stdin=subprocess.DEVNULL,
            text=True, capture_output=True, timeout=10,
        )
        self.assertFalse(self.marker.exists(), "static checks executed a script")
        return result

    def test_shellcheck_catches_unquoted_expansion_that_shell_syntax_accepts(self):
        self.script("bin/unsafe.sh", valid=False)
        result = self.run_check()
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("SC2086", result.stdout)

    def test_valid_scripts_with_spaces_newlines_and_option_like_names_pass(self):
        for name in ("bin/space name.sh", "tools/line\nbreak.sh", "dev/--help"):
            self.script(name)
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_root_and_nested_gitignores_hide_bad_scripts(self):
        self.script("setup", valid=False)
        self.script("tools/cache/bad.sh", valid=False)
        self.script("lib/nested/bad.sh", valid=False)
        self.script("bin/good.sh")
        (self.root / ".gitignore").write_text("setup\ncache/\n")
        (self.root / "lib/.gitignore").write_text("nested/\n")
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        # Changing the actual ignore authority, not checker policy, exposes it.
        (self.root / ".gitignore").write_text("cache/\n")
        result = self.run_check()
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("SC2086", result.stdout)
        self.assertNotIn("cache/bad.sh", result.stdout)
        self.assertNotIn("nested/bad.sh", result.stdout)

    def test_gitignore_negation_reincludes_a_script(self):
        self.script("bin/ignored.sh", valid=False)
        self.script("bin/covered.sh", valid=False)
        ignore = self.root / ".gitignore"
        ignore.write_text("bin/*.sh\n")
        self.assertEqual(0, self.run_check().returncode)
        ignore.write_text("bin/*.sh\n!bin/covered.sh\n")
        result = self.run_check()
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("bin/covered.sh", result.stdout)
        self.assertNotIn("bin/ignored.sh", result.stdout)

    def test_ripgrep_ignore_files_cannot_unignore_gitignored_scripts(self):
        self.script("bin/ignored.sh", valid=False)
        (self.root / ".gitignore").write_text("bin/ignored.sh\n")
        (self.root / ".ignore").write_text("!bin/ignored.sh\n")
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_hidden_scripts_are_checked_without_reading_ripgrep_configuration(self):
        self.script("bin/.hidden", valid=False)
        config = self.root / "rg-config"
        config.write_text("--glob=!bin/.hidden\n")
        result = self.run_check(RIPGREP_CONFIG_PATH=str(config))
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("SC2086", result.stdout)

    def test_non_scripts_and_roots_outside_existing_scope_are_not_checked(self):
        self.script("bin/data.sh", valid=False, shebang=False)
        self.script("vendor/third-party.sh", valid=False)
        result = self.run_check()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_discovery_failure_is_not_consumed_as_a_successful_partial_listing(self):
        self.script("bin/unsafe.sh", valid=False)
        binary = self.root / "fake-bin/rg"
        self.copy(FIXTURES / "failed_shell_discovery.sh", binary)
        binary.chmod(0o755)
        result = self.run_check(PATH=str(binary.parent) + os.pathsep + os.environ["PATH"])
        self.assertEqual(2, result.returncode)
        self.assertEqual("fixture discovery failed\n", result.stderr)
        self.assertNotIn("SC2086", result.stdout)

    def test_missing_dependencies_report_actionable_errors(self):
        for missing, available in (("rg", "shellcheck"), ("shellcheck", "rg")):
            with self.subTest(missing=missing):
                binaries = self.root / missing
                binaries.mkdir()
                (binaries / available).symlink_to(shutil.which(available))
                result = self.run_check(PATH=str(binaries))
                self.assertEqual(1, result.returncode)
                self.assertIn(f"{missing} is required", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
