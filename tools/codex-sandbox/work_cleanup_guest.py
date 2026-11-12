"""Final, exclusive maintenance of registered workspaces in guest work volumes.

The launcher excludes consumers before invoking this program. Native JJ owns
snapshotting and tracked-file identity; Git supplies its compatible ignore
matcher, never deletion or index-based tracked-file identity.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def output(arguments, root, *, environment=None):
    result = subprocess.run(arguments, cwd=root, env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(f"{arguments[0]} failed in {root}: {os.fsdecode(result.stderr).strip()}")
    return result.stdout


def native_jj(root, *arguments):
    return output([os.environ.get("JJ_REAL", "/opt/agent-tools/libexec/jj"),
                   "--no-pager", "--color=never", *arguments], root)


def mountpoints():
    # st_dev alone misses bind mounts on the same filesystem.
    def decode(value):
        for escaped, character in (("\\040", " "), ("\\011", "\t"),
                                   ("\\012", "\n"), ("\\134", "\\")):
            value = value.replace(escaped, character)
        return Path(value)
    return {decode(line.split()[4]) for line in Path("/proc/self/mountinfo").read_text().splitlines()}


def within(path, root):
    return path.is_relative_to(root) and path.resolve(strict=True) == path


def workspace_candidates(root, volume, workspace_roots, *, mounts=None):
    """Snapshot before classification; unlink only ignored, nontracked leaves.

    Caller holds the backing-repository request lock and volume exclusion.
    Nested mounts, repositories and registered workspace roots are never walked.
    """
    if not within(root, volume):
        raise ValueError(f"workspace is not a real directory inside volume: {root}")
    mounts = mountpoints() if mounts is None else mounts
    if any(root.is_relative_to(mount) and mount != volume
           for mount in mounts if mount.is_relative_to(volume)):
        raise ValueError(f"workspace crosses a nested mount: {root}")
    tracked = {Path(json.loads(line)) for line in native_jj(
        root, "file", "list", "-T", r'json(path) ++ "\n"').splitlines()}
    git_dir = os.fsdecode(native_jj(root, "git", "root", "--ignore-working-copy")).strip()
    with tempfile.TemporaryDirectory(prefix="work-cleanup-index-") as temporary:
        environment = os.environ.copy()
        for selector in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            environment.pop(selector, None)
        environment["GIT_INDEX_FILE"] = str(Path(temporary) / "index")
        ignored = {Path(os.fsdecode(path)) for path in output([
            "git", "--git-dir=" + git_dir, "--work-tree=" + str(root),
            "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
        ], root, environment=environment).split(b"\0") if path}
    # Reject malformed classifier output before deleting anything.
    if any(path.is_absolute() or ".." in path.parts for path in ignored | tracked):
        raise ValueError("file classifier returned a path outside the workspace")
    candidates = []
    def walk_error(error):
        raise error
    for directory, children, files in os.walk(root, followlinks=False, onerror=walk_error):
        current = Path(directory)
        files.extend(name for name in children if (current / name).is_symlink())
        children[:] = [name for name in children
                       if name not in {".jj", ".git"}
                       and current / name not in mounts
                       and current / name not in workspace_roots
                       and not (current / name).is_symlink()
                       and not (current / name / ".jj").exists()
                       and not (current / name / ".git").exists()]
        for name in files:
            path = current / name
            relative = path.relative_to(root)
            if (name not in {".jj", ".git"} and path not in mounts
                    and relative in ignored and relative not in tracked):
                candidates.append(path)
    return candidates


def clean_volume(authority):
    """Discover all registered roots before any deletion under this authority."""
    seed, volume = Path(authority["root"]), Path(authority["volume"])
    roots = [json.loads(line) for line in native_jj(
        seed, "workspace", "list", "--ignore-working-copy", "-T",
        r'json(root) ++ "\n"').splitlines()]
    if any(root is None for root in roots):
        raise ValueError("registered workspace lacks a recorded root; files retained")
    selected = {Path(root) for root in roots if Path(root).is_relative_to(volume)}
    expected_repo = Path(authority["jj_repo"]).resolve(strict=True)
    for root in selected:
        if not within(root, volume):
            raise ValueError(f"registered workspace is unavailable: {root}")
        pointer = root / ".jj/repo"
        repo = (pointer.parent / pointer.read_text()
                if pointer.is_file() else pointer).resolve(strict=True)
        if not repo.samefile(expected_repo):
            raise ValueError(f"workspace backing repository changed: {root}")
    candidates = [path for root in sorted(selected)
                  for path in workspace_candidates(root, volume, selected)]
    # Discovery and every snapshot/classification must succeed before deletion.
    for path in candidates:
        path.unlink()
    return len(candidates)


def main():
    failures = []
    for authority in json.loads(sys.argv[1]):
        try:
            with Path(authority["lock"]).open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                count = clean_volume(authority)
            print(f"Work cleanup: {authority['volume']}: removed {count} ignored files", flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append(authority["volume"])
            print(f"Work cleanup incomplete for {authority['volume']}: {error}; files retained where possible", file=sys.stderr)
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
