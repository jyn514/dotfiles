import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/git-hooks"))
sys.path.insert(0, str(ROOT / "config/githooks/pre_commit_hooks"))
from git_hooks import pre_commit  # noqa: E402
import check_added_large_files  # noqa: E402
import check_case_conflict  # noqa: E402


class PreCommitTest(unittest.TestCase):
    def test_case_policy_normalizes_unicode_and_full_case(self) -> None:
        self.assertEqual(
            check_case_conflict.normalized_name("Caf\N{LATIN SMALL LETTER E WITH ACUTE}"),
            check_case_conflict.normalized_name("CAFE\N{COMBINING ACUTE ACCENT}"),
        )
        self.assertEqual(
            check_case_conflict.normalized_name("Stra\N{LATIN SMALL LETTER SHARP S}e"),
            check_case_conflict.normalized_name("STRASSE"),
        )

    def test_lfs_filter_round_trips_undecodable_names_as_bytes(self) -> None:
        filename = os.fsdecode(b"asset-\xff.bin")
        result = mock.Mock(stdout=b"asset-\xff.bin\0filter\0lfs\0")
        filenames = {filename}

        with mock.patch.object(check_added_large_files.subprocess, "run", return_value=result) as run:
            check_added_large_files.filter_lfs_files(filenames)

        self.assertEqual(set(), filenames)
        self.assertEqual(b"asset-\xff.bin", run.call_args.kwargs["input"])

    @unittest.skipIf(sys.platform == "darwin", "macOS requires UTF-8 filenames")
    def test_snapshot_entries_preserve_byte_names_and_sort_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = os.fsencode(temporary)
            undecodable = os.path.join(root, b"line\n\xff")
            descriptor = os.open(undecodable, os.O_WRONLY | os.O_CREAT, 0o600)
            os.close(descriptor)
            os.symlink(b"line\n\xff", os.path.join(root, b"link"))

            files, links = pre_commit.snapshot_entries(root)

        self.assertEqual([b"./line\n\xff"], files)
        self.assertEqual([b"./link"], links)

    def test_interrupted_checkout_cleans_snapshot_and_restores_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            git_directory = directory / "git"
            common_directory = directory / "common"
            git_directory.mkdir()
            common_directory.mkdir()
            original = Path.cwd()
            os.chdir(directory)
            self.addCleanup(os.chdir, original)

            def run(arguments: list[bytes], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
                if arguments[:3] == [b"git", b"diff", b"--quiet"]:
                    return subprocess.CompletedProcess(arguments, 1, b"")
                if arguments == [b"git", b"rev-parse", b"--git-dir"]:
                    return subprocess.CompletedProcess(arguments, 0, os.fsencode(git_directory) + b"\n")
                if arguments == [b"git", b"rev-parse", b"--git-common-dir"]:
                    return subprocess.CompletedProcess(arguments, 0, os.fsencode(common_directory) + b"\n")
                if arguments[:4] == [b"git", b"diff", b"--name-only", b"-z"]:
                    return subprocess.CompletedProcess(arguments, 0, b"file\0")
                if arguments[:2] == [b"git", b"checkout-index"]:
                    raise pre_commit.Interrupted(signal.SIGTERM)
                self.fail(f"unexpected command: {arguments!r}")

            with (
                mock.patch.dict(os.environ, {"TMPDIR": temporary}),
                mock.patch.object(pre_commit, "run", side_effect=run),
            ):
                status = pre_commit.main([], hook_directory=ROOT / "config/githooks")

            self.assertEqual(128 + signal.SIGTERM, status)
            self.assertEqual(directory.resolve(), Path.cwd())
            self.assertEqual([], list(directory.glob("*-pre-commit.*")))

    def test_disposable_repository_accepts_adversarial_staged_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            repository_bytes = os.fsencode(repository)
            names = [
                b"space name.txt",
                b"line\nbreak.txt",
                b"-leading.json",
                "decomposed-e\N{COMBINING ACUTE ACCENT}.txt".encode(),
            ]
            if sys.platform != "darwin":
                names.append(b"undecodable-\xff.txt")
            for name in names:
                descriptor = os.open(
                    os.path.join(repository_bytes, name),
                    os.O_WRONLY | os.O_CREAT,
                    0o644,
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(b"{}\n" if name.endswith(b".json") else b"content\n")
            os.symlink(b"space name.txt", os.path.join(repository_bytes, b"valid-link"))
            subprocess.run([b"git", b"-C", repository_bytes, b"add", b"--all"], check=True)

            result = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=repository,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual([], list(Path(temporary).glob("repository-pre-commit.*")))

            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
            empty = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=repository,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )
            self.assertEqual(0, empty.returncode, empty.stdout + empty.stderr)

            os.rename(
                os.path.join(repository_bytes, b"space name.txt"),
                os.path.join(repository_bytes, b"renamed space.txt"),
            )
            os.unlink(os.path.join(repository_bytes, b"line\nbreak.txt"))
            subprocess.run([b"git", b"-C", repository_bytes, b"add", b"--all"], check=True)
            renamed = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=repository,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )
            self.assertEqual(0, renamed.returncode, renamed.stdout + renamed.stderr)

            head = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"]
            ).strip()
            subprocess.run(
                [
                    b"git",
                    b"-C",
                    repository_bytes,
                    b"update-index",
                    b"--add",
                    b"--cacheinfo",
                    b"160000," + head + b",vendor/submodule",
                ],
                check=True,
            )
            gitlink = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=repository,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )
            self.assertEqual(0, gitlink.returncode, gitlink.stdout + gitlink.stderr)

            local_hook = repository / ".git/hooks/pre-commit"
            local_hook.write_text("#!/bin/sh\nexit 37\n")
            local_hook.chmod(0o755)
            local_failure = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=repository,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )
            self.assertEqual(37, local_failure.returncode)
            local_hook.unlink()

            (repository / "broken.xml").write_text("<open>\n")
            subprocess.run(["git", "-C", str(repository), "add", "broken.xml"], check=True)
            checker_failure = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=repository,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )
            self.assertNotEqual(0, checker_failure.returncode)
            self.assertIn(b"Failed to xml parse", checker_failure.stdout)
            self.assertEqual([], list(Path(temporary).glob("repository-pre-commit.*")))

    def test_linked_worktree_uses_its_index_and_common_hook_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            linked = root / "linked"
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            (repository / "tracked.txt").write_text("before\n")
            subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "-qb", "linked", str(linked)],
                check=True,
            )
            (linked / "tracked.txt").write_text("after\n")
            subprocess.run(["git", "-C", str(linked), "add", "tracked.txt"], check=True)

            result = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=linked,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual([], list(root.glob("linked-pre-commit.*")))

    def test_bare_git_directory_can_check_its_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bare = root / "bare.git"
            subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
            blob = subprocess.check_output(
                ["git", "--git-dir", str(bare), "hash-object", "-w", "--stdin"],
                input=b"content\n",
            ).strip()
            subprocess.run(
                [
                    b"git",
                    b"--git-dir",
                    os.fsencode(bare),
                    b"update-index",
                    b"--add",
                    b"--cacheinfo",
                    b"100644," + blob + b",staged.txt",
                ],
                check=True,
            )

            result = subprocess.run(
                [str(ROOT / "config/githooks/pre-commit")],
                cwd=bare,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ | {"TMPDIR": temporary},
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual([], list(root.glob("bare.git-pre-commit.*")))


if __name__ == "__main__":
    unittest.main()
