"""CLI compatibility for the private history-rewrite backend and its two callers."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ("rewrite-commits", "coauthored-by-author")


class RewriteHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "jj-calls"
        self.data = self.root / "data"
        self.data.mkdir()
        # Resolve the intended entrypoints, including symlinked installations,
        # without relying on the developer's installed filter-repo or JJ state.
        for command in COMMANDS:
            (self.bin / command).symlink_to(ROOT / "bin" / command)
        (self.bin / "git-filter-repo").symlink_to(ROOT / "bin/git-filter-repo")
        jj = self.bin / "jj"
        jj.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$JJ_CALLS"\n'
                      'if [ "${FAIL_JJ:-}" = "$*" ]; then\n'
                      '  echo "fixture JJ failure" >&2\n  exit 7\nfi\n')
        jj.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(
            PATH=f"{self.bin}:{os.environ['PATH']}",
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            JJ_CALLS=str(self.calls), TMPDIR=str(self.data),
            GIT_AUTHOR_NAME="jyn", GIT_AUTHOR_EMAIL="github@jyn.dev",
            GIT_COMMITTER_NAME="Pi Fixture", GIT_COMMITTER_EMAIL="breq@jyn.dev",
        )
        self.git("init", "-q")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env,
                              text=True, capture_output=True, check=True).stdout.strip()

    def commit(self, subject: str = "selected", match: bool = True) -> str:
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m",
                 subject + ("\n\nCo-Authored-By: Claude Fixture <claude@example.test>" if match else ""))
        return self.git("rev-parse", "HEAD")

    def run_command(self, command: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(self.bin / command), *args], cwd=self.repo,
                              env=self.env, text=True, capture_output=True)

    def test_cli_preview_order_hash_width_and_head_scope(self) -> None:
        first = self.commit("first café")
        second = self.commit("second 🐛")
        self.git("branch", "selected")
        hidden = self.commit("hidden")
        self.git("checkout", "-q", "selected")
        rewrite = self.run_command("rewrite-commits")
        coauthor = self.run_command("coauthored-by-author")
        for result in (rewrite, coauthor):
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stderr)
            self.assertNotIn(hidden, result.stdout)
        # Existing log framing retains the separator's leading LF on later
        # records, including rewrite's 12-character abbreviation. Preserve this
        # output quirk here; correcting it is separate from backend extraction.
        self.assertEqual(
            f"{second[:12]}  jyn <github@jyn.dev> / Pi Fixture <breq@jyn.dev>  second 🐛\n"
            f"\n{first[:11]}  jyn <github@jyn.dev> / Pi Fixture <breq@jyn.dev>  first café\n",
            rewrite.stdout,
        )
        self.assertEqual(
            f"{first}  jyn <github@jyn.dev>  ->  Claude Fixture <claude@example.test>\n"
            f"\n{second}  jyn <github@jyn.dev>  ->  Claude Fixture <claude@example.test>\n",
            coauthor.stdout,
        )
        self.assertEqual(second, self.git("rev-parse", "HEAD"))
        self.assertFalse(self.calls.exists())

    def test_matching_dirty_apply_preserves_history_and_refuses_before_jj(self) -> None:
        original = self.commit()
        (self.repo / "untracked").write_text("dirty\n")
        for command in COMMANDS:
            with self.subTest(command=command):
                result = self.run_command(command, "--apply")
                self.assertEqual(1, result.returncode)
                self.assertEqual("Refusing to rewrite history with a dirty Git worktree.\n", result.stderr)
                self.assertEqual(original, self.git("rev-parse", "HEAD"))
        self.assertFalse(self.calls.exists())
        self.assertEqual([], list(self.data.iterdir()))

    def test_no_match_clean_apply_keeps_distinct_output_and_jj_export(self) -> None:
        self.env.update(GIT_AUTHOR_NAME="Other", GIT_AUTHOR_EMAIL="other@example.test")
        original = self.commit(match=False)
        for command, empty in (("rewrite-commits", "No matching commits found."),
                               ("coauthored-by-author", "No matching Co-Authored-By trailers found.")):
            with self.subTest(command=command):
                preview = self.run_command(command)
                self.assertEqual(0, preview.returncode, preview.stderr)
                self.assertEqual(empty + "\n", preview.stdout)
                applied = self.run_command(command, "--apply")
                self.assertEqual(0, applied.returncode, applied.stderr)
                expected = "Nothing to rewrite.\n"
                if command == "coauthored-by-author":
                    expected = empty + "\n" + expected
                self.assertEqual(expected, applied.stdout)
                self.assertEqual(original, self.git("rev-parse", "HEAD"))
        self.assertEqual("git export\n", self.calls.read_text())

    def test_no_match_dirty_apply_keeps_distinct_policy_and_output(self) -> None:
        # Neither identity/trailer matches. Rewrite checks cleanliness before
        # export/scanning; coauthor previews and exits before the cleanliness check.
        self.env.update(GIT_AUTHOR_NAME="Other", GIT_AUTHOR_EMAIL="other@example.test")
        original = self.commit(match=False)
        (self.repo / "untracked").write_text("dirty\n")
        rewrite = self.run_command("rewrite-commits", "--apply")
        self.assertEqual(1, rewrite.returncode)
        self.assertEqual("", rewrite.stdout)
        self.assertEqual("Refusing to rewrite history with a dirty Git worktree.\n", rewrite.stderr)
        coauthor = self.run_command("coauthored-by-author", "--apply")
        self.assertEqual(0, coauthor.returncode, coauthor.stderr)
        self.assertEqual("No matching Co-Authored-By trailers found.\nNothing to rewrite.\n", coauthor.stdout)
        self.assertEqual(original, self.git("rev-parse", "HEAD"))
        self.assertFalse(self.calls.exists())

    def test_jj_export_failure_stops_rewrite_and_reports_command_once(self) -> None:
        original = self.commit()
        self.env["FAIL_JJ"] = "git export"
        result = self.run_command("rewrite-commits", "--apply")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual("Command failed: jj git export\nfixture JJ failure\n\n", result.stderr)
        self.assertEqual("git export\n", self.calls.read_text())
        self.assertEqual(original, self.git("rev-parse", "HEAD"))

    def test_rewrite_forces_filter_and_synchronizes_jj_but_coauthor_keeps_clone_check(self) -> None:
        self.commit("first")
        original = self.commit("second")
        # Multiple reflog entries deliberately fail native filter-repo's
        # fresh-clone check. Coauthor must not acquire rewrite's --force policy.
        coauthor = self.run_command("coauthored-by-author", "--apply")
        self.assertEqual(1, coauthor.returncode)
        self.assertIn("Command failed: git filter-repo --refs HEAD --commit-callback", coauthor.stderr)
        self.assertIn("does not look like a fresh clone", coauthor.stderr)
        self.assertEqual(original, self.git("rev-parse", "HEAD"))
        self.assertFalse(self.calls.exists())
        self.assertEqual([], list(self.data.iterdir()))
        rewrite = self.run_command("rewrite-commits", "--apply")
        self.assertEqual(0, rewrite.returncode, rewrite.stderr)
        self.assertNotEqual(original, self.git("rev-parse", "HEAD"))
        self.assertEqual("Pi Fixture|breq@jyn.dev|jyn|github@jyn.dev",
                         self.git("show", "-s", "--format=%an|%ae|%cn|%ce", "HEAD"))
        self.assertEqual("git export\ngit import\n", self.calls.read_text())

    def test_rewrite_imports_rewritten_head_into_native_colocated_jj(self) -> None:
        native_jj = shutil.which("jj")
        if not native_jj:
            self.skipTest("requires native JJ")
        original = self.commit()
        initialized = subprocess.run(
            [native_jj, "git", "init", "--colocate", str(self.repo)],
            cwd=self.repo, env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        (self.bin / "jj").unlink()
        (self.bin / "jj").symlink_to(native_jj)
        (self.repo / ".jj/repo/config.toml").write_text(
            '[user]\nname = "Fixture"\nemail = "fixture@example.test"\n'
        )
        result = self.run_command("rewrite-commits", "--apply")
        self.assertEqual(0, result.returncode, result.stderr)
        rewritten = self.git("rev-parse", "HEAD")
        self.assertNotEqual(original, rewritten)
        self.assertEqual("Pi Fixture|breq@jyn.dev|jyn|github@jyn.dev",
                         self.git("show", "-s", "--format=%an|%ae|%cn|%ce", "HEAD"))
        imported = subprocess.run(
            [native_jj, "log", "--no-graph", "-r", "@-", "-T", "commit_id"],
            cwd=self.repo, env=self.env, text=True, capture_output=True,
        )
        self.assertEqual(0, imported.returncode, imported.stderr)
        self.assertEqual(rewritten, imported.stdout)

    def test_help_and_unknown_arguments_do_not_need_repository(self) -> None:
        self.repo = self.root
        for command in COMMANDS:
            with self.subTest(command=command):
                help_result = self.run_command(command, "--help")
                self.assertEqual(0, help_result.returncode, help_result.stderr)
                self.assertTrue(help_result.stdout.startswith(f"Usage: {command} "))
                self.assertEqual("", help_result.stderr)
                invalid = self.run_command(command, "--unknown")
                self.assertEqual(1, invalid.returncode)
                self.assertEqual("", invalid.stdout)
                expected = "Unknown arguments" if command == "rewrite-commits" else "Unknown argument"
                self.assertEqual(f"{expected}: --unknown\n", invalid.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
