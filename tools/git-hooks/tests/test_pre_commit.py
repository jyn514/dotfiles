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
sys.path.insert(0, str(ROOT / "tools/git-hooks/pre_commit_hooks"))
from git_hooks import pre_commit  # noqa: E402
import check_added_large_files  # noqa: E402
import check_case_conflict  # noqa: E402


class PreCommitTest(unittest.TestCase):
    def test_git_environment_preserves_selected_path_identity(self) -> None:
        for selector in ("GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
            for raw in (b"relative/../selected-\xff\n", b"/absolute/selected-\xff\n", b""):
                with self.subTest(selector=selector, raw=raw):
                    with mock.patch.dict(os.environ, {}, clear=True):
                        os.environ[selector] = os.fsdecode(raw)
                        environment = pre_commit.git_environment(b"/original/.git", b"/original")
                        key = os.fsencode(selector) if hasattr(os, "environb") else selector
                        expected = b"/original/" + raw if raw and not os.path.isabs(raw) else raw
                        actual = environment[key]
                        self.assertEqual(expected, os.fsencode(actual))
                        self.assertEqual(os.fsdecode(raw), os.environ[selector])
        with mock.patch.dict(os.environ, {}, clear=True):
            environment = pre_commit.git_environment(b"/original/.git", b"/original")
            self.assertNotIn(b"GIT_INDEX_FILE", environment)
            self.assertNotIn("GIT_INDEX_FILE", environment)

    def test_git_environment_text_fallback_preserves_selected_paths(self) -> None:
        inherited = {
            "GIT_INDEX_FILE": os.fsdecode(b"relative/../index-\xff\n"),
            "GIT_COMMON_DIR": "relative/common",
            "GIT_OBJECT_DIRECTORY": "/absolute/objects",
        }
        text_os = mock.Mock(
            spec=("environ", "fsdecode", "path"),
            environ=inherited, fsdecode=os.fsdecode, path=os.path,
        )
        with mock.patch.object(pre_commit, "os", text_os):
            environment = pre_commit.git_environment(b"/original/.git", b"/original")
        self.assertEqual("/original/" + inherited["GIT_INDEX_FILE"], environment["GIT_INDEX_FILE"])
        self.assertEqual("/original/relative/common", environment["GIT_COMMON_DIR"])
        self.assertEqual("/absolute/objects", environment["GIT_OBJECT_DIRECTORY"])
        self.assertEqual("/original/.git", environment["GIT_DIR"])
        self.assertEqual("/original", environment["GIT_WORK_TREE"])
        self.assertNotIn("GIT_DIR", inherited)

    def test_native_commit_checks_selected_index_modes_and_commits_that_tree(self) -> None:
        for selector in ("default", "relative", "absolute"):
            for executable, content, diagnostic in (
                (False, b"content\n", None),
                (True, b"#!/bin/sh\n", None),
                (True, b"content\n", b"Files marked executable but have no (or invalid) shebang:"),
                (False, b"#!/bin/sh\n", b"has a shebang but is not marked executable!"),
            ):
                with (
                    self.subTest(selector=selector, executable=executable, content=content),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    repository = Path(temporary) / "repository"
                    repository.mkdir()
                    environment = {
                        key: value for key, value in os.environ.items()
                        if not key.startswith("GIT_")
                    } | {
                        "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_TERMINAL_PROMPT": "0",
                        "TMPDIR": temporary,
                    }

                    def git(*args: str, env: dict[str, str] = environment) -> bytes:
                        result = subprocess.run(
                            ["git", *args], cwd=repository, env=env, capture_output=True,
                        )
                        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                        return result.stdout

                    git("init", "-q", "--template=")
                    for key, value in (
                        ("user.name", "Test"),
                        ("user.email", "test@example.invalid"),
                        ("commit.gpgsign", "false"),
                        ("core.fileMode", "true"),
                        ("core.autocrlf", "false"),
                        ("core.hooksPath", str(ROOT / "config/githooks")),
                    ):
                        git("config", key, value)
                    (repository / "base").write_bytes(b"base\n")
                    git("add", "--", "base")
                    git("commit", "-qm", "base")
                    base_head = git("rev-parse", "HEAD")
                    default_environment = environment.copy()
                    if selector != "default":
                        alternate = repository / ".git/alternate-index"
                        alternate.write_bytes((repository / ".git/index").read_bytes())
                        # A different valid default-index selection must neither
                        # enter the alternate commit nor be overwritten by it.
                        (repository / "default-only").write_bytes(b"default only\n")
                        git("add", "--", "default-only")
                        environment["GIT_INDEX_FILE"] = (
                            ".git/alternate-index" if selector == "relative" else str(alternate)
                        )
                    selected = repository / "selected"
                    selected.write_bytes(content)
                    selected.chmod(0o755 if executable else 0o644)
                    git("add", "--", "selected")
                    selected_index = git("ls-files", "--stage", "-z")
                    default_index = git("ls-files", "--stage", "-z", env=default_environment)
                    selected_tree = git("write-tree").strip()
                    if selector != "default":
                        self.assertNotEqual(selected_tree, git("write-tree", env=default_environment).strip())
                    result = subprocess.run(
                        ["git", "commit", "-m", "selected"],
                        cwd=repository, env=environment, capture_output=True,
                    )
                    output = result.stdout + result.stderr
                    self.assertEqual(0 if diagnostic is None else 1, result.returncode, output)
                    self.assertNotIn(b"Traceback", output)
                    self.assertEqual(selected_index, git("ls-files", "--stage", "-z"))
                    self.assertEqual(
                        default_index, git("ls-files", "--stage", "-z", env=default_environment),
                    )
                    if diagnostic is not None:
                        self.assertIn(diagnostic, output)
                        self.assertEqual(base_head, git("rev-parse", "HEAD"))
                    else:
                        self.assertEqual(selected_tree, git("rev-parse", "HEAD^{tree}").strip())
                        self.assertEqual(content, git("show", "HEAD:selected"))
                        tree_entry = git("ls-tree", "HEAD", "--", "selected")
                        self.assertTrue(tree_entry.startswith(b"100755 " if executable else b"100644 "))
                    self.assertEqual([], list(Path(temporary).glob("repository-pre-commit.*")))

    def test_native_commit_preserves_relative_common_and_object_directories(self) -> None:
        for selector, value in (("GIT_COMMON_DIR", ".git"), ("GIT_OBJECT_DIRECTORY", ".git/objects")):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as temporary:
                repository = Path(temporary) / "repository"
                repository.mkdir()
                environment = {
                    key: value for key, value in os.environ.items()
                    if not key.startswith("GIT_")
                } | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "TMPDIR": temporary}

                def git(*args: str) -> bytes:
                    result = subprocess.run(
                        ["git", *args], cwd=repository, env=environment, capture_output=True,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    return result.stdout

                git("init", "-q", "--template=")
                for key, setting in (
                    ("user.name", "Test"),
                    ("user.email", "test@example.invalid"),
                    ("commit.gpgsign", "false"),
                    ("core.hooksPath", str(ROOT / "config/githooks")),
                ):
                    git("config", key, setting)
                environment[selector] = value
                # Isolate the adjacent selector from the relative-index defect.
                environment["GIT_INDEX_FILE"] = str(repository / ".git/index")
                (repository / "valid").write_bytes(b"content\n")
                git("add", "--", "valid")
                selected_index = git("ls-files", "--stage", "-z")
                selected_tree = git("write-tree").strip()
                git("commit", "-qm", "valid")
                self.assertEqual(selected_tree, git("rev-parse", "HEAD^{tree}").strip())
                self.assertEqual(selected_index, git("ls-files", "--stage", "-z"))
                self.assertEqual(b"content\n", git("show", "HEAD:valid"))
                self.assertEqual([], list(Path(temporary).glob("repository-pre-commit.*")))

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
                status = pre_commit.main([], hook_directory=ROOT / "tools/git-hooks")

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

    def test_symlink_only_changes_do_not_check_unchanged_regular_files(self) -> None:
        for executable in (False, True):
            with self.subTest(unchanged_file_executable=executable):
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
                    unchanged = repository / "unchanged"
                    unchanged.write_text("#!/bin/sh\n" if executable else "content\n")
                    unchanged.chmod(0o755 if executable else 0o644)
                    subprocess.run(["git", "-C", str(repository), "add", "unchanged"], check=True)
                    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
                    # Both staged links resolve within the partial snapshot, with
                    # no regular files: this isolates empty checker dispatch from
                    # the separate missing unchanged-target snapshot problem.
                    (repository / "directory-target").symlink_to(".")
                    (repository / "directory-link").symlink_to("directory-target")
                    subprocess.run(
                        ["git", "-C", str(repository), "add", "directory-target", "directory-link"],
                        check=True,
                    )

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

    def test_nonempty_regular_file_selection_still_checks_shebang_modes(self) -> None:
        for executable in (False, True):
            with self.subTest(staged_file_executable=executable):
                with tempfile.TemporaryDirectory() as temporary:
                    repository = Path(temporary) / "repository"
                    subprocess.run(["git", "init", "-q", str(repository)], check=True)
                    staged = repository / "staged"
                    staged.write_text("content\n" if executable else "#!/bin/sh\n")
                    staged.chmod(0o755 if executable else 0o644)
                    subprocess.run(["git", "-C", str(repository), "add", "staged"], check=True)

                    result = subprocess.run(
                        [str(ROOT / "config/githooks/pre-commit")],
                        cwd=repository,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=os.environ | {"TMPDIR": temporary},
                        check=False,
                    )

                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    expected = (
                        b"Files marked executable but have no (or invalid) shebang:"
                        if executable else b"has a shebang but is not marked executable!"
                    )
                    self.assertIn(expected, result.stdout + result.stderr)
                    self.assertEqual([], list(Path(temporary).glob("repository-pre-commit.*")))

    def test_literal_selected_names_do_not_expand_to_unchanged_index_files(self) -> None:
        for name in ("ordinary-change", "*", "[ab]", ":(glob)*", "tab\tfile"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
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
                unchanged = repository / "a"
                unchanged.write_text("#!/bin/sh\n")
                unchanged.chmod(0o755)
                subprocess.run(["git", "-C", str(repository), "add", "a"], check=True)
                subprocess.run(["git", "-C", str(repository), "commit", "-qm", "base"], check=True)
                selected = repository / name
                # First accept a valid selected file, then prove both mode
                # checkers still reject that exact file rather than skipping it.
                for executable, content, expected in (
                    (False, "content\n", None),
                    (True, "content\n", b"Files marked executable but have no (or invalid) shebang:"),
                    (False, "#!/bin/sh\n", b"has a shebang but is not marked executable!"),
                ):
                    with self.subTest(executable=executable, content=content):
                        selected.write_text(content)
                        selected.chmod(0o755 if executable else 0o644)
                        subprocess.run(
                            ["git", "-C", str(repository), "--literal-pathspecs", "add", "--", name],
                            check=True,
                        )
                        result = subprocess.run(
                            [str(ROOT / "config/githooks/pre-commit")],
                            cwd=repository,
                            capture_output=True,
                            env=os.environ | {"TMPDIR": temporary},
                            check=False,
                        )
                        output = result.stdout + result.stderr
                        self.assertEqual(0 if expected is None else 1, result.returncode, output)
                        self.assertNotIn(b"Traceback", output)
                        if expected is not None:
                            self.assertIn(expected, output)
                            self.assertIn(os.fsencode(name), output)
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
