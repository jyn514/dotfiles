import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_pre_commit_preserves_newlines_in_filenames(self) -> None:
        checkout = self.directory / "checkout"
        git_directory = self.directory / "git-directory"
        common_directory = self.directory / "common-directory"
        git_directory.mkdir()
        common_directory.mkdir()
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            f'  "rev-parse --git-dir") printf "%s\\n" "{git_directory}";;\n'
            f'  "rev-parse --git-common-dir") printf "%s\\n" "{common_directory}";;\n'
            '  "diff --name-only") printf "line\\nbreak\\0";;\n'
            '  "checkout-index "*) printf "<%s>\\n" "$4" > "$CHECKOUT";;\n'
            'esac\n',
        )
        self.executable(
            "xargs",
            'checker=\n'
            'for argument do [ ! -f "$argument" ] || checker=$argument; done\n'
            '[ -n "$checker" ] || exit 41\n'
            "cat >/dev/null\n",
        )

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CHECKOUT": str(checkout),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("<line\nbreak>\n", checkout.read_text())
    def test_pre_commit_propagates_git_diff_failure(self) -> None:
        self.executable("git", "exit 23\n")

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(23, result.returncode)
    def test_pre_commit_checks_broken_symlinks(self) -> None:
        git_directory = self.directory / "git-directory"
        common_directory = self.directory / "common-directory"
        git_directory.mkdir()
        common_directory.mkdir()
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            f'  "rev-parse --git-dir") printf "%s\\n" "{git_directory}";;\n'
            f'  "rev-parse --git-common-dir") printf "%s\\n" "{common_directory}";;\n'
            '  "diff --name-only") printf "broken-link\\0";;\n'
            '  "checkout-index "*) prefix=${2#--prefix=}; ln -s missing "$prefix$4";;\n'
            'esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Broken symlink", result.stdout)
    def test_pre_commit_rejects_malformed_xml(self) -> None:
        git_directory = self.directory / "git-directory"
        common_directory = self.directory / "common-directory"
        git_directory.mkdir()
        common_directory.mkdir()
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            f'  "rev-parse --git-dir") printf "%s\\n" "{git_directory}";;\n'
            f'  "rev-parse --git-common-dir") printf "%s\\n" "{common_directory}";;\n'
            '  "diff --name-only") printf "broken.xml\\0";;\n'
            '  "checkout-index "*) prefix=${2#--prefix=}; printf "<open>\\n" > "$prefix$4";;\n'
            'esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Failed to xml parse", result.stdout)
    def test_pre_commit_propagates_git_directory_query_failure(self) -> None:
        realpath_calls = self.directory / "realpath-calls"
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            '  "rev-parse --git-dir") exit 29;;\n'
            "esac\n",
        )
        self.executable(
            "realpath", 'printf "%s\\n" "$*" > "$REALPATH_CALLS"\nprintf "/wrong\\n"\n'
        )

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "REALPATH_CALLS": str(realpath_calls),
            },
        )

        self.assertEqual(29, result.returncode)
        self.assertFalse(realpath_calls.exists())
    def test_case_conflict_keeps_newlines_inside_filenames(self) -> None:
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "ls-files -z") printf "foo\\nbar\\0";;\n'
            '  "diff --staged") printf "FOO\\nbaz\\0";;\n'
            'esac\n',
        )

        result = subprocess.run(
            [
                "python3",
                str(
                    ROOT
                    / "tools/git-hooks/pre_commit_hooks/check_case_conflict.py"
                ),
                "FOO\nbaz",
            ],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
    def test_pre_push_does_not_split_newlines_into_rust_filenames(self) -> None:
        calls = self.directory / "cargo-calls"
        (self.directory / "Cargo.toml").touch()
        self.executable("git", 'printf "fake.rs\\nnot-rust\\0"\n')
        self.executable("cargo", 'printf "%s\\n" "$*" > "$CARGO_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CARGO_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(calls.exists())
    def test_pre_push_formats_rust_files_in_the_pushed_range(self) -> None:
        calls = self.directory / "calls"
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$CALLS"\n'
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{"a" * 40}\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", 'printf "cargo %s\\n" "$*" >> "$CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"diff --name-only -z --no-ext-diff {'b' * 40} {'a' * 40}\n"
            "rev-parse HEAD\n"
            "status --porcelain --untracked-files=all\n"
            "cargo fmt --check\n",
            calls.read_text(),
        )
    def test_pre_push_reads_every_ref_before_formatting(self) -> None:
        calls = self.directory / "calls"
        (self.directory / "Cargo.toml").touch()
        rust_sha = "c" * 40
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$CALLS"\n'
            'case "$1" in\n'
            f'  diff) [ "$6" != "{rust_sha}" ] || printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{rust_sha}\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", 'printf "cargo %s\\n" "$*" >> "$CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=(
                f"refs/heads/one {'a' * 40} refs/heads/one {'b' * 40}\n"
                f"refs/heads/two {rust_sha} refs/heads/two {'d' * 40}\n"
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {"CALLS": str(calls), "PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, calls.read_text().count("diff --name-only"))
        self.assertTrue(calls.read_text().endswith("cargo fmt --check\n"))
    def test_pre_push_rejects_rust_commit_that_is_not_checked_out(self) -> None:
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{"c" * 40}\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", "exit 99\n")

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("not checked out", result.stderr)
    def test_pre_push_rejects_dirty_rust_worktree(self) -> None:
        sha = "a" * 40
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{sha}\\n";;\n'
            '  status) printf "?? untracked.rs\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", "exit 99\n")

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {sha} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("dirty worktree", result.stderr)
    def test_pre_push_formats_jj_working_copy_commit(self) -> None:
        sha = "a" * 40
        calls = self.directory / "calls"
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{"b" * 40}\\n";;\n'
            'esac\n',
        )
        self.executable("jj", f'printf "{sha}\\n"\n')
        self.executable("cargo", 'printf "%s\\n" "$*" > "$CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {sha} refs/heads/main {'c' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {"CALLS": str(calls), "PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("fmt --check\n", calls.read_text())


if __name__ == "__main__":
    unittest.main()
