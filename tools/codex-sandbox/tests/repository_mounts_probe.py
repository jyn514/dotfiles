"""Check Git discovery and write protection inside the repository mount fixture."""

import os
from pathlib import Path
import subprocess
import sys


layout = sys.argv[1]
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
