import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/git-autosquash"
LOADER = importlib.machinery.SourceFileLoader(
    "git_autosquash_command", str(MODULE_PATH)
)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
git_autosquash = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = git_autosquash
LOADER.exec_module(git_autosquash)


class GitAutosquashTests(unittest.TestCase):
    def test_derives_branch_remote_and_base_before_revising(self):
        runner = mock.Mock(
            side_effect=[
                git_autosquash.Result(0, b"topic\n"),
                git_autosquash.Result(0, b"upstream\n"),
                git_autosquash.Result(0, b"abc123\n"),
                git_autosquash.Result(0),
            ]
        )

        self.assertEqual(git_autosquash.autosquash([], runner), 0)
        self.assertEqual(
            runner.call_args_list,
            [
                mock.call(
                    ["git", "symbolic-ref", "--short", "--quiet", "HEAD"],
                    capture_output=True,
                ),
                mock.call(
                    ["git", "config", "--get", "branch.topic.remote"],
                    capture_output=True,
                ),
                mock.call(
                    ["git", "merge-base", "HEAD", "upstream/HEAD"],
                    capture_output=True,
                ),
                mock.call(["git", "revise", "abc123", "-i"]),
            ],
        )

    def test_detached_head_uses_most_recent_branch(self):
        runner = mock.Mock(
            side_effect=[
                git_autosquash.Result(1),
                git_autosquash.Result(0, b"recent\n"),
                git_autosquash.Result(1),
                git_autosquash.Result(0, b"base\n"),
                git_autosquash.Result(0),
            ]
        )

        self.assertEqual(git_autosquash.autosquash([], runner), 0)
        self.assertEqual(
            runner.call_args_list[-2],
            mock.call(
                ["git", "merge-base", "HEAD", "origin/HEAD"],
                capture_output=True,
            ),
        )

    def test_query_failures_stop_at_their_boundary(self):
        for results, expected in (
            ([git_autosquash.Result(2), git_autosquash.Result(24)], 24),
            ([git_autosquash.Result(0, b"main\n"), git_autosquash.Result(25)], 25),
            (
                [
                    git_autosquash.Result(0, b"main\n"),
                    git_autosquash.Result(0, b"origin\n"),
                    git_autosquash.Result(26),
                ],
                26,
            ),
        ):
            with self.subTest(expected=expected):
                runner = mock.Mock(side_effect=results)
                self.assertEqual(git_autosquash.autosquash([], runner), expected)
                self.assertEqual(runner.call_count, len(results))

    def test_explicit_base_and_rebase_preserve_remaining_arguments(self):
        runner = mock.Mock(return_value=git_autosquash.Result(31))

        self.assertEqual(
            git_autosquash.autosquash(
                ["--rebase", "base ref", "--autosquash"], runner
            ),
            31,
        )
        runner.assert_called_once_with(
            ["git", "rebase", "base ref", "-i", "--autosquash"]
        )

    def test_empty_explicit_argument_keeps_legacy_extra_argument_behavior(self):
        runner = mock.Mock(
            side_effect=[
                git_autosquash.Result(0, b"main\n"),
                git_autosquash.Result(1),
                git_autosquash.Result(0, b"base\n"),
                git_autosquash.Result(0),
            ]
        )

        self.assertEqual(git_autosquash.autosquash(["", "extra"], runner), 0)
        self.assertEqual(
            runner.call_args_list[-1],
            mock.call(["git", "revise", "base", "-i", "", "extra"]),
        )

    def test_captured_values_preserve_undecodable_bytes(self):
        value = git_autosquash.captured_value(
            git_autosquash.Result(0, b"ref-\xff\n\n")
        )

        self.assertEqual(os.fsencode(value), b"ref-\xff")

    def test_missing_git_returns_shell_compatible_status(self):
        with mock.patch.object(
            git_autosquash.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = git_autosquash.run(["git"])

        self.assertEqual(result.status, 127)
        self.assertIn("could not execute 'git'", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
