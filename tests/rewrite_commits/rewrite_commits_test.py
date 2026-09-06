import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMAND = ROOT / "bin/rewrite-commits"


class RewriteCommitsTest(unittest.TestCase):
    def run_command(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        fake_bin = repo.parent / "bin"
        fake_bin.mkdir(exist_ok=True)
        jj = fake_bin / "jj"
        jj.write_text("#!/bin/sh\nexit 0\n")
        jj.chmod(0o755)
        return subprocess.run(
            [str(COMMAND), *args],
            cwd=repo,
            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def git(self, repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            env={**os.environ, **(env or {})},
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return result.stdout.strip()

    def test_rewrites_only_the_misattributed_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.name", "jyn")
            self.git(repo, "config", "user.email", "github@jyn.dev")

            (repo / "file").write_text("base\n")
            self.git(repo, "add", "file")
            self.git(repo, "commit", "-q", "-m", "base")
            (repo / "file").write_text("base\nagent\n")
            self.git(repo, "add", "file")
            identity = {
                "GIT_AUTHOR_NAME": "jyn",
                "GIT_AUTHOR_EMAIL": "github@jyn.dev",
                "GIT_AUTHOR_DATE": "2026-01-02T00:00:00Z",
                "GIT_COMMITTER_NAME": "Pi test",
                "GIT_COMMITTER_EMAIL": "breq@jyn.dev",
                "GIT_COMMITTER_DATE": "2026-01-02T01:00:00Z",
            }
            self.git(repo, "commit", "-q", "-m", "affected", env=identity)
            preserved = self.git(repo, "show", "-s", "--format=%aI|%cI|%T|%s", "HEAD")

            preview = self.run_command(repo)
            self.assertEqual(0, preview.returncode, preview.stderr)
            self.assertIn("jyn <github@jyn.dev> / Pi test <breq@jyn.dev>", preview.stdout)
            self.assertEqual("jyn|github@jyn.dev|Pi test|breq@jyn.dev", self.git(
                repo, "show", "-s", "--format=%an|%ae|%cn|%ce", "HEAD"
            ))

            applied = self.run_command(repo, "--apply")
            self.assertEqual(0, applied.returncode, applied.stderr)
            self.assertEqual("Pi test|breq@jyn.dev|jyn|github@jyn.dev", self.git(
                repo, "show", "-s", "--format=%an|%ae|%cn|%ce", "HEAD"
            ))
            self.assertEqual(preserved, self.git(
                repo, "show", "-s", "--format=%aI|%cI|%T|%s", "HEAD"
            ))


if __name__ == "__main__":
    unittest.main()
