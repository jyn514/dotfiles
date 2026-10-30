import json
import os
import runpy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


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

    def test_apply_removes_only_native_footer_occurrences(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        body = f"Boundary café 🐛\n\nCo-Authored-By: {PERSON}\nThe example ends here.\n\n"
        unrelated = (
            "Co-Authored-By: Human Helper <helper@example.test>\n"
            f"Co-Authored-By: {PERSON} extra\n"
            "Reviewed-by:   Reviewer <reviewer@example.test>  \n"
        )
        patch = (
            "\n---\n example.txt | 1 +\n\ndiff --git a/example.txt b/example.txt\n"
            "--- a/example.txt\n+++ b/example.txt\n@@ -0,0 +1 @@\n+example\n"
        )
        # Classify duplicate footer lines against the original message: deleting
        # the final block first would promote the earlier body paragraph.
        earlier = f"Duplicate footer\n\nCo-Authored-By: {PERSON}\n\n"
        fixtures = (
            (body + f"Co-Authored-By: {PERSON}\n" + unrelated, body + unrelated),
            (body + f"Co-Authored-By: {PERSON}\n" + unrelated + patch, body + unrelated + patch),
            (earlier + f"Co-Authored-By: {PERSON}\n" * 2, earlier),
        )
        ids = []
        for message, _ in fixtures:
            self.git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                     "--cleanup=verbatim", "-F", "-", input=message)
            ids.append(self.git("rev-parse", "HEAD").strip())
        source = self.repo
        for keep in (False, True):
            with self.subTest(keep_trailer=keep):
                clone = source.parent / f"boundary-clone-{keep}"
                self.git("clone", "--no-local", "-q", str(source), str(clone))
                self.repo = clone
                before = self.git("log", "--reverse", "--format=%T|%aI|%cn|%ce|%cI|%B")
                self.assert_candidates(self.run_command(), ids)
                self.assertEqual(before, self.git("log", "--reverse", "--format=%T|%aI|%cn|%ce|%cI|%B"))
                metadata = self.git("log", "--reverse", "--format=%T|%aI|%cn|%ce|%cI|%s")
                self.assert_candidates(self.run_command("--apply", *(["--keep-trailer"] if keep else [])), ids)
                self.assertEqual(metadata, self.git("log", "--reverse", "--format=%T|%aI|%cn|%ce|%cI|%s"))
                commits = self.git("rev-list", "--reverse", "HEAD").splitlines()
                self.assertEqual(len(fixtures), len(commits))
                for commit, (message, removed) in zip(commits, fixtures):
                    raw = subprocess.run(
                        ["git", "cat-file", "commit", commit], cwd=self.repo, env=self.env,
                        capture_output=True, check=True,
                    ).stdout
                    self.assertEqual((message if keep else removed).encode("utf-8"), raw.split(b"\n\n", 1)[1])
                    self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", commit))
                self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_apply_preserves_native_comment_lines(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        heading = "Comment café 🐛\n\n"
        upper = f"Co-Authored-By: {PERSON}\n"
        lower = f"co-authored-by: {PERSON}\n"
        reviewer = "Reviewed-by: Reviewer <reviewer@example.test>\n"
        message = heading + upper + lower + reviewer
        self.git("-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                 "--cleanup=verbatim", "-F", "-", input=message)
        commit = self.git("rev-parse", "HEAD").strip()
        source = self.repo
        for index, (prefix, parsed, expected) in enumerate((
            (upper.rstrip("\n"), lower + reviewer, heading + upper + reviewer),
            # An extension of the original line can newly become a comment
            # after appending a marker. It must not suppress a real trailer.
            (lower.rstrip("\n") + "A", upper + lower + reviewer, heading + reviewer),
        )):
            with self.subTest(comment_string=prefix):
                clone = source.parent / f"comment-clone-{index}"
                self.git("clone", "--no-local", "-q", str(source), str(clone))
                self.repo = clone
                self.git("config", "core.commentString", prefix)
                self.assertEqual(parsed, self.git("interpret-trailers", "--parse", input=message))
                def raw_commit() -> bytes:
                    return subprocess.run(
                        ["git", "cat-file", "commit", "HEAD"], cwd=self.repo, env=self.env,
                        capture_output=True, check=True,
                    ).stdout

                before = raw_commit()
                self.assert_candidates(self.run_command(), [commit])
                self.assertEqual(before, raw_commit())
                self.assert_candidates(self.run_command("--apply"), [commit])
                after = raw_commit()
                self.assertEqual(expected.encode("utf-8"), after.split(b"\n\n", 1)[1])
                before_headers = before.split(b"\n\n", 1)[0].split(b"\n")
                after_headers = after.split(b"\n\n", 1)[0].split(b"\n")
                self.assertEqual(
                    [line for line in before_headers if not line.startswith(b"author ")],
                    [line for line in after_headers if not line.startswith(b"author ")],
                )
                self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
                self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_apply_preserves_native_line_endings_and_identity_case(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        heading = "Compatibility café 🐛\r\n\r\n".encode("utf-8")
        upper = f"Co-Authored-By: {PERSON}\r\n".encode("utf-8")
        lower = f"co-authored-by: {PERSON}\r\n".encode("utf-8")
        reviewer = b"Reviewed-by: Reviewer <reviewer@example.test>\r\n"
        canonical = f"Co-Authored-By: {PERSON}\n".encode("utf-8")
        changed_case = f"Co-Authored-By: {PERSON.upper()}\n".encode("utf-8")
        fixtures = (
            ("CRLF", heading + canonical[:-1] + b" \t\r\n", heading, None, canonical),
            ("identity-case", heading + canonical + changed_case, heading, None, canonical + changed_case),
            ("comment-CR", heading + upper + lower + reviewer, heading + upper + reviewer,
             upper[:-1].decode("utf-8"), lower.replace(b"\r\n", b"\n") + reviewer.replace(b"\r\n", b"\n")),
        )
        parent = self.repo.parent
        for name, message, removed, comment, parsed in fixtures:
            source = parent / name
            source.mkdir()
            self.repo = source
            self.git("init", "-q")
            self.git("config", "user.name", "Original Author")
            self.git("config", "user.email", "original@example.test")
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                 "--cleanup=verbatim", "-F", "-"], cwd=source, env=self.env,
                input=message, capture_output=True, check=True,
            )
            commit = self.git("rev-parse", "HEAD").strip()
            for keep in (False, True):
                with self.subTest(case=name, keep_trailer=keep):
                    clone = parent / f"{name}-clone-{keep}"
                    self.git("clone", "--no-local", "-q", str(source), str(clone))
                    self.repo = clone
                    if comment is not None:
                        self.git("config", "core.commentString", comment)
                    native = subprocess.run(
                        ["git", "interpret-trailers", "--parse"], cwd=clone, env=self.env,
                        input=message, capture_output=True, check=True,
                    ).stdout
                    self.assertEqual(parsed, native)

                    def raw_commit() -> bytes:
                        return subprocess.run(
                            ["git", "cat-file", "commit", "HEAD"], cwd=clone, env=self.env,
                            capture_output=True, check=True,
                        ).stdout

                    before = raw_commit()
                    self.assertEqual(message, before.split(b"\n\n", 1)[1])
                    self.assert_candidates(self.run_command(), [commit])
                    self.assertEqual(before, raw_commit())
                    self.assert_candidates(self.run_command("--apply", *(["--keep-trailer"] if keep else [])), [commit])
                    after = raw_commit()
                    self.assertEqual(message if keep else removed, after.split(b"\n\n", 1)[1])
                    self.assertEqual(
                        [line for line in before.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                        [line for line in after.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                    )
                    self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
                    self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_apply_removes_native_horizontal_identity_spacing(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        identities = [f"Claude Example{space}<claude@example.test>" for space in ("", "\t", "  ", "  \t ")]
        matching = "".join(f"Co-Authored-By: {identity}\n" for identity in identities)
        body = f"Horizontal café 🐛\n\nCo-Authored-By: {identities[-1]}\nThis is a body example.\n\n"
        unrelated = (
            f"Co-Authored-By: {identities[-1]} extra\n"
            "Co-Authored-By: Human Helper <helper@example.test>\n"
            "Reviewed-by: Reviewer <reviewer@example.test>\n"
        )
        message = (body + matching + unrelated).encode("utf-8")
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
             "--cleanup=verbatim", "-F", "-"], cwd=self.repo, env=self.env,
            input=message, capture_output=True, check=True,
        )
        commit = self.git("rev-parse", "HEAD").strip()
        source = self.repo
        for keep in (False, True):
            with self.subTest(keep_trailer=keep):
                clone = source.parent / f"horizontal-clone-{keep}"
                self.git("clone", "--no-local", "-q", str(source), str(clone))
                self.repo = clone
                native = subprocess.run(
                    ["git", "interpret-trailers", "--parse"], cwd=clone, env=self.env,
                    input=message, capture_output=True, check=True,
                ).stdout
                self.assertEqual((matching + unrelated).encode("utf-8"), native)

                def raw_commit() -> bytes:
                    return subprocess.run(
                        ["git", "cat-file", "commit", "HEAD"], cwd=clone, env=self.env,
                        capture_output=True, check=True,
                    ).stdout

                before = raw_commit()
                self.assertEqual(message, before.split(b"\n\n", 1)[1])
                self.assert_candidates(self.run_command(), [commit])
                self.assertEqual(before, raw_commit())
                self.assert_candidates(self.run_command("--apply", *(["--keep-trailer"] if keep else [])), [commit])
                after = raw_commit()
                self.assertEqual(message if keep else (body + unrelated).encode("utf-8"), after.split(b"\n\n", 1)[1])
                self.assertEqual(
                    [line for line in before.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                    [line for line in after.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                )
                self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
                self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_apply_removes_only_matching_native_folded_fields(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        fold = b"Co-Authored-By: Claude\n Example\n <claude@example.test>\n"
        normalized = f"Co-Authored-By: {PERSON}\n".encode("utf-8")
        reviewer = b"Reviewed-by: Reviewer <reviewer@example.test>\n"
        body = "Folded café 🐛\n\n".encode("utf-8") + fold + b"Not a trailer block.\n\n"
        unrelated = fold[:-1] + b"\n extra note\n" + reviewer
        patch = b"\n---\n" + fold + b"\ndiff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -0,0 +1 @@\n+example\n"
        edge = b"Co-Authored-By:\t\r\n \tClaude Example\t<claude@example.test> \t\r\n"
        edge_normalized = b"Co-Authored-By: Claude Example\t<claude@example.test>\n"
        cr_fold = b"Co-Authored-By: Claude Example \t\r\n \t<claude@example.test> \t\r\n"
        cr_fold_normalized = b"Co-Authored-By: Claude Example \t\r <claude@example.test>\n"
        cr_heading = "Folded edges café 🐛\r\n\r\n".encode("utf-8")
        cr_reviewer = reviewer.replace(b"\n", b"\r\n")
        comment = b"Co-Authored-By: Claude Example\n <claude@example.test>\n"
        actual = comment.replace(b"Co-Authored-By", b"co-authored-by")
        fixtures = (
            ("body-footer-diff", body + fold + unrelated + patch, body + unrelated + patch, None,
             normalized + normalized[:-1] + b" extra note\n" + reviewer),
            ("edge-CRLF", cr_heading + edge + cr_reviewer, cr_heading + cr_reviewer, None,
             edge_normalized + reviewer),
            # A canonical field establishes the identity; also remove its
            # duplicate with a name/email fold across CRLF.
            ("name-email-CRLF", cr_heading + normalized + cr_fold + cr_reviewer,
             cr_heading + cr_reviewer, None, normalized + cr_fold_normalized + reviewer),
            ("comment-start", body + comment + b"\n" + actual + reviewer, body + comment + b"\n" + reviewer,
             "Co-Authored-By: Claude Example", normalized.replace(b"Co-Authored-By", b"co-authored-by") + reviewer),
            ("new-comment-prefix", body + comment + reviewer, body + reviewer,
             "Co-Authored-By: Claude ExampleA", normalized + reviewer),
        )
        parent = self.repo.parent
        for name, message, removed, prefix, parsed in fixtures:
            source = parent / name
            source.mkdir()
            self.repo = source
            self.git("init", "-q")
            self.git("config", "user.name", "Original Author")
            self.git("config", "user.email", "original@example.test")
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                 "--cleanup=verbatim", "-F", "-"], cwd=source, env=self.env,
                input=message, capture_output=True, check=True,
            )
            commit = self.git("rev-parse", "HEAD").strip()
            for keep in (False, True):
                with self.subTest(case=name, keep_trailer=keep):
                    clone = parent / f"{name}-clone-{keep}"
                    self.git("clone", "--no-local", "-q", str(source), str(clone))
                    self.repo = clone
                    if prefix is not None:
                        self.git("config", "core.commentString", prefix)
                    native = subprocess.run(
                        ["git", "interpret-trailers", "--parse"], cwd=clone, env=self.env,
                        input=message, capture_output=True, check=True,
                    ).stdout
                    self.assertEqual(parsed, native)

                    def raw_commit() -> bytes:
                        return subprocess.run(
                            ["git", "cat-file", "commit", "HEAD"], cwd=clone, env=self.env,
                            capture_output=True, check=True,
                        ).stdout

                    before = raw_commit()
                    self.assertEqual(message, before.split(b"\n\n", 1)[1])
                    self.assert_candidates(self.run_command(), [commit])
                    self.assertEqual(before, raw_commit())
                    self.assert_candidates(self.run_command("--apply", *(["--keep-trailer"] if keep else [])), [commit])
                    after = raw_commit()
                    self.assertEqual(message if keep else removed, after.split(b"\n\n", 1)[1])
                    self.assertEqual(
                        [line for line in before.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                        [line for line in after.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                    )
                    self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
                    self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_standalone_crlf_name_email_fold_reaches_apply(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        fold = b"Co-Authored-By: Claude Example \t\r\n \t<claude@example.test> \t\r\n"
        reviewer = b"Reviewed-by: Reviewer <reviewer@example.test>\r\n"
        body = "Standalone fold café 🐛\r\n\r\n".encode("utf-8") + fold + b"Not a trailer block.\r\n\r\n"
        message = body + fold + reviewer
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
             "--cleanup=verbatim", "-F", "-"], cwd=self.repo, env=self.env,
            input=message, capture_output=True, check=True,
        )
        commit = self.git("rev-parse", "HEAD").strip()
        source = self.repo
        for keep in (False, True):
            with self.subTest(keep_trailer=keep):
                clone = source.parent / f"standalone-CRLF-clone-{keep}"
                self.git("clone", "--no-local", "-q", str(source), str(clone))
                self.repo = clone
                native = subprocess.run(
                    ["git", "interpret-trailers", "--parse"], cwd=clone, env=self.env,
                    input=message, capture_output=True, check=True,
                ).stdout
                self.assertEqual(
                    b"Co-Authored-By: Claude Example \t\r <claude@example.test>\n"
                    + reviewer.replace(b"\r\n", b"\n"), native,
                )

                def raw_commit() -> bytes:
                    return subprocess.run(
                        ["git", "cat-file", "commit", "HEAD"], cwd=clone, env=self.env,
                        capture_output=True, check=True,
                    ).stdout

                before = raw_commit()
                self.assertEqual(message, before.split(b"\n\n", 1)[1])
                self.assert_candidates(self.run_command(), [commit])
                self.assertEqual(before, raw_commit())
                self.assert_candidates(self.run_command("--apply", *(["--keep-trailer"] if keep else [])), [commit])
                after = raw_commit()
                self.assertEqual(message if keep else body + reviewer, after.split(b"\n\n", 1)[1])
                self.assertEqual(
                    [line for line in before.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                    [line for line in after.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                )
                self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
                self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_apply_uses_native_key_boundaries_not_literal_colon(self) -> None:
        if not shutil.which("git-filter-repo"):
            self.skipTest("requires native git-filter-repo")
        parent = self.repo.parent
        for name, boundary, separators in (("space", " :", None), ("tab", "\t:", None), ("equals", "=", ":=")):
            matching = f"Co-Authored-By{boundary} {PERSON}\n"
            body = f"Key boundary café 🐛\n\n{matching}This is a body example.\n\n"
            unrelated = (
                f"Co-Authored-By-Extra: {PERSON}\n"
                f"Co-Authored-Byish: {PERSON}\n"
                "Co-Authored-By: Human Helper <helper@example.test>\n"
                "Reviewed-by: Reviewer <reviewer@example.test>\n"
            )
            message = (body + matching + unrelated).encode("utf-8")
            source = parent / name
            source.mkdir()
            self.repo = source
            self.git("init", "-q")
            self.git("config", "user.name", "Original Author")
            self.git("config", "user.email", "original@example.test")
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                 "--cleanup=verbatim", "-F", "-"], cwd=source, env=self.env,
                input=message, capture_output=True, check=True,
            )
            commit = self.git("rev-parse", "HEAD").strip()
            for keep in (False, True):
                with self.subTest(case=name, keep_trailer=keep):
                    clone = parent / f"{name}-clone-{keep}"
                    self.git("clone", "--no-local", "-q", str(source), str(clone))
                    self.repo = clone
                    if separators is not None:
                        self.git("config", "trailer.separators", separators)
                    native = subprocess.run(
                        ["git", "interpret-trailers", "--parse"], cwd=clone, env=self.env,
                        input=message, capture_output=True, check=True,
                    ).stdout
                    self.assertEqual((f"Co-Authored-By: {PERSON}\n" + unrelated).encode("utf-8"), native)

                    def raw_commit() -> bytes:
                        return subprocess.run(
                            ["git", "cat-file", "commit", "HEAD"], cwd=clone, env=self.env,
                            capture_output=True, check=True,
                        ).stdout

                    before = raw_commit()
                    self.assertEqual(message, before.split(b"\n\n", 1)[1])
                    self.assert_candidates(self.run_command(), [commit])
                    self.assertEqual(before, raw_commit())
                    self.assert_candidates(self.run_command("--apply", *(["--keep-trailer"] if keep else [])), [commit])
                    after = raw_commit()
                    self.assertEqual(message if keep else (body + unrelated).encode("utf-8"), after.split(b"\n\n", 1)[1])
                    self.assertEqual(
                        [line for line in before.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                        [line for line in after.split(b"\n\n", 1)[0].split(b"\n") if not line.startswith(b"author ")],
                    )
                    self.assertEqual("Claude Example|claude@example.test\n", self.git("show", "-s", "--format=%an|%ae", "HEAD"))
                    self.assertEqual("", self.git("status", "--porcelain=v1"))

    def test_callback_requires_markers_in_the_same_native_field(self) -> None:
        first = b"Co-Authored-By: Claude Example"
        last = b" <claude@example.test>"
        message = b"Selected\n\n" + first + b"\n" + last + b"\n"
        commit = SimpleNamespace(
            original_id=b"a" * 40, message=message,
            author_name=b"Original Author", author_email=b"original@example.test",
        )
        data_path = self.repo.parent / "authors.json"
        data_path.write_text(json.dumps({
            "authors": {"a" * 40: {"name": "Claude Example", "email": "claude@example.test"}},
            "keep-trailer": False,
        }))

        def separate_fields(args, *, input, stdout):
            lines = input.split(b"\n")
            start_marker = lines[2][len(first):]
            end_marker = lines[3][len(last):]
            self.assertTrue(start_marker)
            self.assertTrue(end_marker)
            # Coauthor identity matches after stripping its start marker, but
            # the end marker belongs to an unrelated field: no span is proven.
            parsed = (first + start_marker + last + b"\n"
                      + b"Reviewed-by: Reviewer" + end_marker + b"\n")
            return subprocess.CompletedProcess(args, 0, stdout=parsed)

        with mock.patch.dict(os.environ, {"COAUTHORED_BY_AUTHOR_DATA": str(data_path)}):
            with mock.patch("subprocess.run", side_effect=separate_fields) as native:
                runpy.run_path(str(ROOT / "libexec/coauthored-by-author.py"), init_globals={"commit": commit})
        self.assertGreater(native.call_count, 0)
        self.assertEqual(message, commit.message)
        self.assertEqual(b"Claude Example", commit.author_name)
        self.assertEqual(b"claude@example.test", commit.author_email)

    def test_callback_refuses_failed_native_occurrence_classification(self) -> None:
        messages = (
            f"Selected\n\nCo-Authored-By: {PERSON}\n".encode("utf-8"),
            b"Selected\n\nCo-Authored-By: Claude Example\n <claude@example.test>\n",
        )
        for message in messages:
            with self.subTest(message=message):
                commit = SimpleNamespace(
                    original_id=b"a" * 40, message=message,
                    author_name=b"Original Author", author_email=b"original@example.test",
                )
                data_path = self.repo.parent / "authors.json"
                data_path.write_text(json.dumps({
                    "authors": {"a" * 40: {"name": "Claude Example", "email": "claude@example.test"}},
                    "keep-trailer": False,
                }))
                # Even plausible output cannot authorize deletion after native failure.
                failed = subprocess.CompletedProcess(
                    ["git", "interpret-trailers", "--parse"], 42,
                    stdout=b"Co-Authored-By: coauthored-by-author-marker\n",
                )
                with mock.patch.dict(os.environ, {"COAUTHORED_BY_AUTHOR_DATA": str(data_path)}):
                    with mock.patch("subprocess.run", return_value=failed):
                        with self.assertRaises(subprocess.CalledProcessError):
                            runpy.run_path(str(ROOT / "libexec/coauthored-by-author.py"), init_globals={"commit": commit})
                self.assertEqual(message, commit.message)
                self.assertEqual(b"Original Author", commit.author_name)
                self.assertEqual(b"original@example.test", commit.author_email)

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
