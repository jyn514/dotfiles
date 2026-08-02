import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/git-hooks"))
from git_hooks import pre_push  # noqa: E402


class PrePushTest(unittest.TestCase):
    def test_parse_updates_preserves_ref_and_oid_bytes(self) -> None:
        update = b"refs/heads/topic " + b"a" * 40 + b" refs/heads/topic " + b"b" * 40

        self.assertEqual(
            [(b"refs/heads/topic", b"a" * 40, b"refs/heads/topic", b"b" * 40)],
            pre_push.parse_updates(update + b"\n"),
        )

    def test_parse_updates_rejects_malformed_records(self) -> None:
        with self.assertRaisesRegex(ValueError, "line 1"):
            pre_push.parse_updates(b"refs/heads/main only-two-fields\n")

    def test_rust_detection_uses_nul_delimited_paths(self) -> None:
        update = [(b"local", b"a" * 40, b"remote", b"b" * 40)]
        result = mock.Mock(returncode=0, stdout=b"looks.rs\nnot-rust\0actual.txt\0")

        with mock.patch.object(pre_push, "command", return_value=result):
            status, revision = pre_push.rust_revision(update)

        self.assertEqual(0, status)
        self.assertIsNone(revision)

    def test_deletion_does_not_query_git(self) -> None:
        update = [(b"local", b"0" * 64, b"remote", b"b" * 64)]

        with mock.patch.object(pre_push, "command") as command:
            status, revision = pre_push.rust_revision(update)

        self.assertEqual((0, None), (status, revision))
        command.assert_not_called()

    def test_new_branch_diffs_from_empty_tree(self) -> None:
        update = [(b"local", b"a" * 40, b"remote", b"0" * 40)]
        empty_tree = mock.Mock(returncode=0, stdout=b"tree-id\n")
        changed = mock.Mock(returncode=0, stdout=b"src/lib.rs\0")

        with mock.patch.object(pre_push, "command", side_effect=[empty_tree, changed]) as command:
            status, revision = pre_push.rust_revision(update)

        self.assertEqual((0, b"a" * 40), (status, revision))
        self.assertEqual(
            [b"git", b"diff", b"--name-only", b"-z", b"--no-ext-diff", b"tree-id", b"a" * 40],
            command.call_args_list[1].args[0],
        )

    def test_git_diff_failure_is_propagated(self) -> None:
        update = [(b"local", b"a" * 40, b"remote", b"b" * 40)]
        failed = mock.Mock(returncode=27, stdout=b"partial.rs\0")

        with mock.patch.object(pre_push, "command", return_value=failed):
            status, revision = pre_push.rust_revision(update)

        self.assertEqual((27, None), (status, revision))

    def test_multiple_distinct_rust_revisions_are_rejected(self) -> None:
        updates = [
            (b"one", b"a" * 40, b"one", b"c" * 40),
            (b"two", b"b" * 40, b"two", b"d" * 40),
        ]
        result = mock.Mock(returncode=0, stdout=b"src/lib.rs\0")

        with mock.patch.object(pre_push, "command", return_value=result):
            status, revision = pre_push.rust_revision(updates)

        self.assertEqual((1, None), (status, revision))

    def test_disposable_repository_formats_checked_out_rust_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            repository = temporary_path / "repository"
            tools = temporary_path / "tools"
            tools.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            (repository / "Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.1.0'\n")
            source = repository / "src/lib.rs"
            source.parent.mkdir()
            source.write_text("pub fn before() {}\n")
            subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
            base = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"]).strip()
            source.write_text("pub fn after() {}\n")
            subprocess.run(["git", "-C", str(repository), "commit", "-qam", "change"], check=True)
            head = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"]).strip()
            calls = temporary_path / "cargo-calls"
            cargo = tools / "cargo"
            cargo.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$CARGO_CALLS\"\n")
            cargo.chmod(0o755)

            result = subprocess.run(
                [str(ROOT / "config/githooks/pre-push")],
                cwd=repository,
                input=b"refs/heads/main " + head + b" refs/heads/main " + base + b"\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ
                | {
                    "CARGO_CALLS": str(calls),
                    "PATH": f"{tools}:{os.environ['PATH']}",
                },
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("fmt --check\n", calls.read_text())


if __name__ == "__main__":
    unittest.main()
