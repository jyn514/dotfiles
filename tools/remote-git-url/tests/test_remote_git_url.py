from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "remote_git_url/main.py"
SPEC = importlib.util.spec_from_file_location("remote_git_url_main", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
remote_git_url = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(remote_git_url)


class RemoteGitUrlTests(unittest.TestCase):
    def test_parses_https_scp_and_ssh_repository_urls(self) -> None:
        cases = {
            b"https://github.com/group/repo.git": (b"github.com", b"group/repo"),
            b"git@gitlab.com:group/nested/repo.git": (
                b"gitlab.com",
                b"group/nested/repo",
            ),
            b"ssh://git@github.com/group/repo.git/": (b"github.com", b"group/repo"),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                parsed = remote_git_url.repository_url(value)
                self.assertEqual(expected, (parsed.host, parsed.path))

    def test_rejects_lookalike_and_incomplete_hosts(self) -> None:
        for value in (
            b"https://evilgithub.com/group/repo.git",
            b"https://github.com/repo.git",
            b"local-path",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                remote_git_url.repository_url(value)

    def test_encodes_nested_paths_and_host_specific_ranges(self) -> None:
        relative = b"docs/file #%?-\xff.txt"
        github = remote_git_url.source_url(
            remote_git_url.RepositoryUrl(b"github.com", b"group/repo"),
            b"abc123",
            relative,
            4,
            3,
        )
        gitlab = remote_git_url.source_url(
            remote_git_url.RepositoryUrl(b"gitlab.com", b"group/nested/repo"),
            b"abc123",
            relative,
            4,
            3,
        )
        self.assertEqual(
            b"https://github.com/group/repo/blob/abc123/docs/file%20%23%25%3F-%FF.txt#L4-L6",
            github,
        )
        self.assertEqual(
            b"https://gitlab.com/group/nested/repo/-/blob/abc123/"
            b"docs/file%20%23%25%3F-%FF.txt#L4-6",
            gitlab,
        )

    def test_locates_the_complete_selected_range(self) -> None:
        remote = b"first\nshared\nwrong\nshared\nright\nlast\n"
        self.assertEqual(4, remote_git_url.locate([b"shared", b"right"], remote))
        self.assertIsNone(remote_git_url.locate([b"shared", b"missing"], remote))
        self.assertIsNone(remote_git_url.locate([b""], remote))

    def test_upstream_eof_does_not_add_a_row_or_remove_a_bare_cr(self) -> None:
        self.assertIsNone(remote_git_url.locate([b"needle", b""], b"needle\n"))
        self.assertEqual(1, remote_git_url.locate([b"needle", b""], b"needle\n\n"))
        self.assertIsNone(remote_git_url.locate([b"needle"], b"prefix\nneedle\r"))

    def test_disposable_repository_links_use_upstream_lf_line_numbers(self) -> None:
        # GitLab's source viewer numbers LF/CRLF rows, not lone CR boundaries.
        # Both hosts historically received native git grep's LF-based numbering.
        cases = (
            ("lone-cr-before-target", b"prefix\rmore\nneedle\ndecoy\n", b"needle\n", 1, 1, 2),
            ("bare-cr-is-not-a-row-start", b"prefix\rneedle\nother\nneedle\n", b"needle\n", 1, 1, 3),
            ("lf", b"prefix\nneedle\ndecoy\n", b"needle\n", 1, 1, 2),
            ("crlf", b"prefix\r\nneedle\r\ndecoy\r\n", b"needle\n", 1, 1, 2),
            ("final-newline", b"prefix\nneedle\n", b"needle\n", 1, 1, 2),
            ("no-final-newline", b"prefix\nneedle", b"needle", 1, 1, 2),
            ("only-one-terminal-cr", b"needle\r\r\nother\nneedle\n", b"needle\n", 1, 1, 3),
            (
                "complete-range",
                b"prefix\rmore\nshared\nwrong\nshared\nright\nlast\n",
                b"intro\nshared\nright\n",
                2, 3, 4,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)

            def git(*arguments: str) -> bytes:
                return subprocess.check_output(["git", "-C", str(repository), *arguments])

            git("init", "-q", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.com")
            for name, upstream, *_ in cases:
                (repository / f"{name}.py").write_bytes(upstream)
            git("add", "--all")
            git("commit", "-qm", "upstream contents")
            (repository / "later").write_bytes(b"later\n")
            git("add", "--all")
            git("commit", "-qm", "later")
            revision = git("rev-parse", "HEAD").strip()
            git("remote", "add", "origin", "https://gitlab.com/group/repo.git")
            git("update-ref", "refs/remotes/origin/main", "HEAD")
            git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            environment = os.environ.copy()
            environment.pop("DISPLAY", None)
            for host in ("gitlab.com", "github.com"):
                git("remote", "set-url", "origin", f"https://{host}/group/repo.git")
                blob_path = "/-/blob/" if host == "gitlab.com" else "/blob/"
                for name, _, local, start, end, expected_line in cases:
                    with self.subTest(host=host, case=name):
                        source = repository / f"{name}.py"
                        source.write_bytes(local)
                        result = subprocess.run(
                            [
                                str(MODULE_PATH.parents[3] / "bin/remote-git-url"),
                                str(source), str(start), str(end),
                            ],
                            cwd=repository,
                            env=environment,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False,
                        )
                        fragment = f"#L{expected_line}"
                        if end != start:
                            separator = "-L" if host == "github.com" else "-"
                            fragment += f"{separator}{expected_line + end - start}"
                        expected = (
                            f"https://{host}/group/repo{blob_path}"
                            + revision.decode()
                            + f"/{name}.py{fragment}\n"
                        ).encode()
                        self.assertEqual(b"", result.stderr)
                        self.assertEqual(1, result.returncode)
                        self.assertEqual(expected, result.stdout)

    def test_disposable_repository_resolves_complete_range_in_remote_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository with spaces"
            subprocess.run(["git", "init", "-q", "-b", "main", repository], check=True)
            subprocess.run(
                ["git", "-C", repository, "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                ["git", "-C", repository, "config", "user.email", "test@example.com"],
                check=True,
            )
            source = repository / "file with spaces\nand newline.txt"
            source.write_text("first\nshared\nwrong\nshared\nright\nlast\n")
            subprocess.run(["git", "-C", repository, "add", "--all"], check=True)
            subprocess.run(["git", "-C", repository, "commit", "-qm", "source"], check=True)
            (repository / "later").write_text("later\n")
            subprocess.run(["git", "-C", repository, "add", "--all"], check=True)
            subprocess.run(["git", "-C", repository, "commit", "-qm", "later"], check=True)
            expected_revision = subprocess.check_output(
                ["git", "-C", repository, "rev-parse", "HEAD"]
            ).strip()
            subprocess.run(
                [
                    "git",
                    "-C",
                    repository,
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:group/repo.git",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    repository,
                    "update-ref",
                    "refs/remotes/origin/main",
                    "HEAD",
                ],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    repository,
                    "symbolic-ref",
                    "refs/remotes/origin/HEAD",
                    "refs/remotes/origin/main",
                ],
                check=True,
            )
            installed = root / "installed-remote-git-url"
            installed.symlink_to(Path(__file__).resolve().parents[3] / "bin/remote-git-url")
            environment = os.environ.copy()
            environment.pop("DISPLAY", None)
            result = subprocess.run(
                [installed, source, "4", "5"],
                cwd="/",
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            b"https://github.com/group/repo/blob/"
            + expected_revision
            + b"/file%20with%20spaces%0Aand%20newline.txt#L4-L5\n",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
