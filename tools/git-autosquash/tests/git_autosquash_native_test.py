"""Check reference identity across native Git queries and the command entrypoint."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class NativeGitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repository = self.directory / "repo"
        self.repository.mkdir()
        self.native_git = shutil.which("git")
        self.assertIsNotNone(self.native_git, "native Git is required")
        # An inherited GIT_DIR, config injection, or object directory must never
        # redirect these native mutations outside the owned disposable fixture.
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        } | {
            "HOME": str(self.directory),
            "XDG_CONFIG_HOME": str(self.directory / "config"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        self.git("init", "--initial-branch=topic")
        tree = self.git("mktree", input="")
        parent = []
        commits = []
        for day, name in enumerate(("root", "selected", "tip"), 1):
            date = f"2000-01-{day:02d}T00:00:00+0000"
            commit = self.git(
                "commit-tree", tree, *parent, input=name + "\n",
                environment={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
            )
            commits.append(commit)
            parent = ["-p", commit]
        self.root, self.selected, self.tip = commits
        self.git("update-ref", "refs/heads/topic", self.tip)
        self.git("update-ref", "refs/heads/older", self.root)
        for remote, commit in (("origin", self.root), ("upstream", self.selected)):
            self.git("update-ref", f"refs/remotes/{remote}/main", commit)
            self.git("symbolic-ref", f"refs/remotes/{remote}/HEAD",
                     f"refs/remotes/{remote}/main")
        self.git("config", "branch.topic.remote", "upstream")
        self.trace_path = self.directory / "trace.jsonl"
        shim_directory = self.directory / "bin"
        shim_directory.mkdir()
        shim = shim_directory / "git"
        shutil.copyfile(Path(__file__).with_name("native_git_shim.py"), shim)
        shim.chmod(0o755)
        self.command_environment = self.environment | {
            "PATH": str(shim_directory) + os.pathsep + os.environ["PATH"],
            "AUTOSQUASH_NATIVE_GIT": self.native_git,
            "AUTOSQUASH_TRACE": str(self.trace_path),
        }

    def git(self, *arguments, input=None, environment=None):
        result = subprocess.run(
            [self.native_git, *arguments], cwd=self.repository,
            env=self.environment | (environment or {}), input=input,
            text=True, capture_output=True, check=True,
        )
        return result.stdout.rstrip("\n")

    def invoke(self, *arguments, status=0):
        self.trace_path.unlink(missing_ok=True)
        before = self.git("show-ref", "--head")
        result = subprocess.run(
            [sys.executable, str(ROOT / "bin/git-autosquash"), *arguments],
            cwd=self.repository,
            env=self.command_environment | {"AUTOSQUASH_EFFECT_STATUS": str(status)},
            text=True, capture_output=True,
        )
        self.assertEqual(before, self.git("show-ref", "--head"))
        self.assertEqual(status, result.returncode, result.stderr)
        self.trace = [json.loads(line) for line in self.trace_path.read_text().splitlines()]
        return self.trace[-1]["argv"]

    def test_remote_head_cannot_be_shadowed_by_local_refs(self):
        for remote in ("origin", "upstream"):
            for namespace in (None, "heads", "tags"):
                for command in ("revise", "rebase"):
                    with self.subTest(remote=remote, namespace=namespace, command=command):
                        # Missing config still selects origin, not an alternate remote.
                        if remote == "origin":
                            self.git("config", "--unset", "branch.topic.remote")
                        else:
                            self.git("config", "branch.topic.remote", remote)
                        shadow = f"refs/{namespace}/{remote}/HEAD" if namespace else None
                        if shadow:
                            self.git("update-ref", shadow, self.tip)
                        try:
                            argv = self.invoke(*(["--rebase"] if command == "rebase" else []))
                            expected = self.root if remote == "origin" else self.selected
                            self.assertEqual([command, expected, "-i"], argv, self.trace)
                        finally:
                            if shadow:
                                self.git("update-ref", "-d", shadow)
                            if remote == "origin":
                                self.git("config", "branch.topic.remote", "upstream")

    def test_branch_config_identity_survives_ambiguous_short_names(self):
        for detached in (False, True):
            for ambiguous in (False, True):
                with self.subTest(detached=detached, ambiguous=ambiguous):
                    if ambiguous:
                        self.git("update-ref", "refs/tags/topic", self.root)
                    if detached:
                        self.git("update-ref", "--no-deref", "HEAD", self.tip)
                    else:
                        self.git("symbolic-ref", "HEAD", "refs/heads/topic")
                    try:
                        self.assertEqual(["revise", self.selected, "-i"], self.invoke(), self.trace)
                    finally:
                        if ambiguous:
                            self.git("update-ref", "-d", "refs/tags/topic")

    def test_explicit_base_arguments_and_effect_status_are_untouched(self):
        self.assertEqual(
            ["rebase", "base ref", "-i", "--autosquash"],
            self.invoke("--rebase", "base ref", "--autosquash", status=31),
        )
        self.assertEqual(1, len(self.trace))


if __name__ == "__main__":
    unittest.main()
