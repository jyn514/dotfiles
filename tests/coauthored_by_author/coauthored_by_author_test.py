import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/coauthored-by-author"
TRAILER_KEYS = ("Co-Authored-By", "co-authored-by", "Co-authored-by", "cO-aUtHoReD-bY")
PERSON = "Claude Example <claude@example.test>"
ORIGINAL = "Original Author <original@example.test>"


@unittest.skipUnless(shutil.which("bb") and shutil.which("git"), "requires native Babashka and Git")
class CoauthoredByAuthorTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo"
        self.repo.mkdir()
        # Do not let ambient Git selectors redirect mutations outside this fixture.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        self.git("init", "-q")
        self.git("config", "user.name", "Original Author")
        self.git("config", "user.email", "original@example.test")

    def git(self, *args: str, input: str | None = None) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, input=input,
            text=True, capture_output=True, check=True,
        ).stdout

    def commit(self, subject: str, body: str, author: str = ORIGINAL) -> str:
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                 "--author", author, "-F", "-", input=f"{subject}\n\n{body}\n")
        return self.git("rev-parse", "HEAD").strip()

    def run_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(COMMAND), *args], cwd=self.repo, env=self.env,
            text=True, capture_output=True,
        )

    def assert_candidates(self, result: subprocess.CompletedProcess[str], ids: list[str]) -> None:
        self.assertEqual(0, result.returncode, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(ids, [line.split()[0] for line in lines])
        for line in lines:
            self.assertTrue(line.endswith(f"{ORIGINAL}  ->  {PERSON}"), line)

    def matching_commits(self) -> list[str]:
        ids = []
        for index, key in enumerate(TRAILER_KEYS):
            body = f"{key}: {PERSON}"
            self.assertEqual(f"{body}\n", self.git("interpret-trailers", "--parse", input=f"subject\n\n{body}\n"))
            ids.append(self.commit(f"variant-{index}", body))
        return ids

    def test_dry_run_uses_native_trailers_not_case_or_body_lookalikes(self) -> None:
        ids = self.matching_commits()
        for subject, body, author in (
            ("nonmatching", "Co-Authored-By: Claudette <other@example.test>", ORIGINAL),
            ("malformed-person", "Co-Authored-By: Claude Example", ORIGINAL),
            ("other-token", f"Reviewed-by: {PERSON}", ORIGINAL),
            ("body-only", f"Co-Authored-By: {PERSON}\n\nNot a trailer block.", ORIGINAL),
            ("already-author", f"co-authored-by: {PERSON}", PERSON),
        ):
            self.commit(subject, body, author)
        before = self.git("log", "--format=%H|%an|%ae|%B")
        self.assert_candidates(self.run_command(), ids)
        self.assertEqual(before, self.git("log", "--format=%H|%an|%ae|%B"))

    def test_explicit_match_and_refs_still_select_only_requested_history(self) -> None:
        selected = self.commit("selected", "co-authored-by: Other Person <other@example.test>")
        self.git("branch", "selected")
        self.commit("later", f"co-authored-by: {PERSON}")
        result = self.run_command("--refs", "selected", "--match", "^Other Person$")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{selected}  {ORIGINAL}  ->  Other Person <other@example.test>\n", result.stdout,
        )
        default = self.run_command("--refs", "selected")
        self.assertEqual(0, default.returncode, default.stderr)
        self.assertEqual("No matching Co-Authored-By trailers found.\n", default.stdout)

    def assert_apply(self, keep_trailer: bool) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        ids = self.matching_commits()
        untouched = self.commit("untouched", "Reviewed-by: Other Person <other@example.test>")
        # Preserve filter-repo's fresh-clone safety check, rather than forcing it.
        clone = self.repo.parent / "clone"
        self.git("clone", "--no-local", "-q", str(self.repo), str(clone))
        self.repo = clone
        before = self.git("log", "--reverse", "--format=%T|%aI|%cn|%ce|%cI|%s")
        result = self.run_command("--apply", *(["--keep-trailer"] if keep_trailer else []))
        self.assert_candidates(result, ids)
        self.assertNotEqual(untouched, self.git("rev-parse", "HEAD").strip())
        self.assertEqual(before, self.git("log", "--reverse", "--format=%T|%aI|%cn|%ce|%cI|%s"))
        commits = self.git("rev-list", "--reverse", "HEAD").splitlines()
        self.assertEqual(5, len(commits))
        for index, commit in enumerate(commits[:-1]):
            self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", commit))
            expected = f"variant-{index}"
            if keep_trailer:
                expected += f"\n\n{TRAILER_KEYS[index]}: {PERSON}"
            self.assertEqual(expected, self.git("show", "-s", "--format=%B", commit).rstrip("\n"))
        self.assertEqual("Original Author|original@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
        self.assertEqual("untouched\n\nReviewed-by: Other Person <other@example.test>\n\n", self.git("show", "-s", "--format=%B", "HEAD"))
        self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_apply_rewrites_case_variants_and_removes_matching_trailers(self) -> None:
        self.assert_apply(keep_trailer=False)

    def test_apply_keep_trailer_preserves_original_spelling(self) -> None:
        self.assert_apply(keep_trailer=True)

    def test_dirty_worktree_refusal_does_not_rewrite(self) -> None:
        commit = self.commit("selected", f"co-authored-by: {PERSON}")
        (self.repo / "untracked").write_text("dirty\n")
        result = self.run_command("--apply")
        self.assertEqual(1, result.returncode)
        self.assertIn("Refusing to rewrite history with a dirty Git worktree.", result.stderr)
        self.assertEqual(commit, self.git("rev-parse", "HEAD").strip())
        self.assertEqual("Original Author|original@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))


if __name__ == "__main__":
    unittest.main()
