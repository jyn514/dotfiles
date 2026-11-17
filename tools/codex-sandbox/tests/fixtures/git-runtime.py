"""Exercise installed Git, not a source-tree binary; all repositories are disposable."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def probe(check_toolchain=False):
    if check_toolchain:
        for command in ("gcc", "g++", "make", "rustc", "cargo"):
            assert shutil.which(command) is None, command
    with tempfile.TemporaryDirectory(prefix="git-runtime-") as directory:
        root = Path(directory)
        environment = os.environ | {
            "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
        def git(*args, cwd=root):
            return run("git", *args, cwd=cwd, env=environment)

        git("init", "main")
        main = root / "main"
        git("commit", "--allow-empty", "-m", "fixture", cwd=main)
        # Reproduce reading an existing relativeWorktrees repository, then use
        # Git itself to create and move linked worktrees with that extension.
        git("config", "core.repositoryformatversion", "1", cwd=main)
        git("config", "extensions.relativeWorktrees", "true", cwd=main)
        git("status", "--porcelain", cwd=main)
        git("worktree", "add", "--relative-paths", "../linked", cwd=main)
        assert git("config", "--get", "extensions.relativeWorktrees", cwd=main) == "true"
        linked = root / "linked"
        assert not (linked / ".git").read_text().split(": ", 1)[1].startswith("/")
        assert git("rev-parse", "HEAD", cwd=linked) == git("rev-parse", "HEAD", cwd=main)
        moved = root / "moved"
        moved.mkdir()
        shutil.move(main, moved / "main")
        shutil.move(linked, moved / "linked")
        assert git("status", "--porcelain", cwd=moved / "linked") == ""
        assert git("worktree", "list", "--porcelain", cwd=moved / "main").count("worktree ") == 2
        # --no-local forces the installed upload-pack helper, rather than a copy.
        git("clone", "--no-local", str(moved / "main"), "local-clone")
        assert git("rev-parse", "HEAD", cwd=root / "local-clone") == git("rev-parse", "HEAD", cwd=moved / "main")
        # An unauthenticated, read-only fetch of GitHub's small example repository
        # exercises libcurl, TLS validation, certificates and remote-https together.
        git("-C", "local-clone", "fetch", "--depth=1", "https://github.com/octocat/Hello-World.git", "HEAD")
        assert git("rev-parse", "FETCH_HEAD", cwd=root / "local-clone")
        print("git-runtime-ok " + git("--version"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-toolchain", action="store_true")
    args = parser.parse_args()
    probe(args.no_toolchain)
