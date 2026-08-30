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


ROOT = Path(__file__).resolve().parents[2]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_git_aliases_preserve_the_remote_default_when_deleting_merged_branches(self) -> None:
        repository = self.directory / "repository"
        remote = self.directory / "remote.git"
        repository.mkdir()
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repository,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
        (repository / "file").write_text("tea\n")
        subprocess.run(["git", "add", "file"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "personal", str(remote)], cwd=repository, check=True)
        subprocess.run(
            [
                "git",
                "push",
                "personal",
                "HEAD:refs/heads/first",
                "HEAD:refs/heads/second",
                "HEAD:refs/heads/-option-like",
            ],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "symbolic-ref",
                "refs/remotes/personal/HEAD",
                "refs/remotes/personal/first",
            ],
            cwd=repository,
            check=True,
        )
        config = f"include.path={ROOT / 'config/gitconfig'}"

        default_branch = subprocess.run(
            ["/usr/bin/git", "-c", config, "default-branch"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        delete_merged = subprocess.run(
            ["/usr/bin/git", "-c", config, "delete-merged"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        remaining = subprocess.run(
            ["git", "ls-remote", "--heads", str(remote)],
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        branch_log = subprocess.run(
            ["/usr/bin/git", "-c", config, "branch-log"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        parent = subprocess.run(
            ["/usr/bin/git", "-c", config, "parent"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, default_branch.returncode)
        self.assertNotEqual(0, branch_log.returncode)
        self.assertNotEqual(0, parent.returncode)
        self.assertEqual(0, delete_merged.returncode, delete_merged.stderr)
        self.assertIn("refs/heads/first", remaining.stdout)
        self.assertNotIn("refs/heads/second", remaining.stdout)
        self.assertNotIn("refs/heads/-option-like", remaining.stdout)
    def test_jj_publish_passes_a_valid_update_to_the_pre_push_hook(self) -> None:
        publish = tomllib.loads((ROOT / "config/jj.toml").read_text())["aliases"][
            "publish"
        ]
        command = publish[-1]
        calls = self.directory / "jj-calls"
        hook_input = self.directory / "hook-input"
        commit = "a" * 40
        self.executable(
            "jj",
            'if [ "$1" = log ]; then\n'
            f'  printf "%s\\n" "{commit}"\n'
            "else\n"
            '  printf "%s\\n" "$*" >> "$JJ_CALLS"\n'
            "fi\n",
        )
        self.executable(
            "git",
            'if [ "$1 $2 $3" = "hook run pre-push" ]; then\n'
            '  cat > "$HOOK_INPUT"\n'
            "else\n"
            "  exit 99\n"
            "fi\n",
        )

        result = subprocess.run(
            ["/bin/bash", "-c", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "HOOK_INPUT": str(hook_input),
                "JJ_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        fields = hook_input.read_text().split()
        self.assertEqual(4, len(fields))
        self.assertEqual(commit, fields[1])
        self.assertEqual("0" * 40, fields[3])
        self.assertEqual(["tug", "push"], calls.read_text().splitlines())
    def test_jj_push_bookmark_sanitizes_conventional_commit_subjects(self) -> None:
        template = tomllib.loads((ROOT / "config/jj.toml").read_text())["templates"][
            "git_push_bookmark"
        ]
        expression = template.replace("description", '"Fix: parser"', 1)

        rendered = subprocess.run(
            ["jj", "log", "--no-graph", "-r", "@", "-T", expression],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        bookmark = rendered.stdout
        self.assertEqual("jyn/Fix-", bookmark)
        valid = subprocess.run(
            ["git", "check-ref-format", f"refs/heads/{bookmark}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, valid.returncode, valid.stderr)


if __name__ == "__main__":
    unittest.main()
