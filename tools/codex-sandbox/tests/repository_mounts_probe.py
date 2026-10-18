"""Check Git discovery and write protection inside the repository mount fixture."""

import os
import json
from pathlib import Path
import subprocess
import sys


def assert_readonly(path):
    try:
        if path.is_dir():
            (path / "forbidden-write").write_text("forbidden")
        else:
            path.write_text("forbidden")
    except OSError:
        return
    raise AssertionError(f"protected path became writable: {path}")


layout = sys.argv[1]
if layout == "shared":
    roots = [Path(path) for path in json.loads(os.environ["WORKSPACE_ROOTS"])]
    for root in roots:
        (root / "created").write_text("writable")
        git_paths = subprocess.run([
            "git", "-C", str(root), "-c", "safe.directory=*", "rev-parse",
            "--path-format=absolute", "--git-dir", "--git-common-dir",
        ], check=True, text=True, capture_output=True).stdout.splitlines()
        for git_path in git_paths:
            assert_readonly(Path(git_path))
        assert_readonly(root / ".git")
        assert_readonly(root / ".jj")
    for path in json.loads(os.environ["PROTECTED_PATHS"]):
        assert_readonly(Path(path))
    assert_readonly(Path("/src/unlisted"))
    skills = Path("/home/codex/.agents/skills/shared")
    skills.write_text("live skills alias")
    assert (roots[1] / "skills/shared").read_text() == "live skills alias"
    raise SystemExit(0)

repo = Path.cwd()
entry = repo / ".git"
assert entry.is_file() if layout == "linked" else entry.is_dir()
git_paths = subprocess.run([
    "git", "-c", "safe.directory=*", "rev-parse", "--path-format=absolute",
    "--git-dir", "--git-common-dir",
], check=True, text=True, capture_output=True).stdout.splitlines()
git_dir, common = (Path(path).resolve(strict=True) for path in git_paths)
assert (git_dir / "HEAD").is_file()
assert (common / "objects").is_dir()
if layout == "linked":
    assert git_dir != common
    assert git_dir.name == "worktree"
    assert common == Path(os.environ["EXPECTED_COMMON"])
for path in (entry, git_dir / "HEAD", common / "config", repo / ".jj/marker"):
    try:
        path.write_text("forbidden")
    except OSError:
        pass
    else:
        raise AssertionError(f"metadata became writable: {path}")
(repo / "created").write_text("writable")
