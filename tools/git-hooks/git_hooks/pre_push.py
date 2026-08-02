"""Select pushed Rust revisions and run their formatting check."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def command(arguments: list[bytes]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, check=False, stdout=subprocess.PIPE)


def parse_updates(data: bytes) -> list[tuple[bytes, bytes, bytes, bytes]]:
    updates: list[tuple[bytes, bytes, bytes, bytes]] = []
    for number, line in enumerate(data.splitlines(), 1):
        if not line:
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(f"malformed pre-push update on line {number}")
        updates.append((fields[0], fields[1], fields[2], fields[3]))
    return updates


def null_oid(oid: bytes) -> bool:
    return bool(oid) and not oid.strip(b"0")


def rust_revision(updates: list[tuple[bytes, bytes, bytes, bytes]]) -> tuple[int, bytes | None]:
    selected: bytes | None = None
    for _local_ref, local_oid, _remote_ref, remote_oid in updates:
        if null_oid(local_oid):
            continue
        if null_oid(remote_oid):
            empty_tree = command([b"git", b"hash-object", b"-t", b"tree", b"/dev/null"])
            if empty_tree.returncode:
                return exit_status(empty_tree.returncode), None
            base = empty_tree.stdout.rstrip(b"\n")
        else:
            base = remote_oid
        changed = command(
            [b"git", b"diff", b"--name-only", b"-z", b"--no-ext-diff", base, local_oid]
        )
        if changed.returncode:
            return exit_status(changed.returncode), None
        if not any(path.endswith(b".rs") for path in changed.stdout.split(b"\0") if path):
            continue
        if selected is not None and selected != local_oid:
            print(
                "error: cannot check Rust formatting for multiple pushed commits",
                file=sys.stderr,
            )
            return 1, None
        selected = local_oid
    return 0, selected


def checked_out(revision: bytes) -> tuple[int, bool]:
    head = command([b"git", b"rev-parse", b"HEAD"])
    if head.returncode:
        return exit_status(head.returncode), False
    if revision == head.stdout.rstrip(b"\n"):
        status = command([b"git", b"status", b"--porcelain", b"--untracked-files=all"])
        if status.returncode:
            return exit_status(status.returncode), False
        if status.stdout:
            print(
                "error: cannot check Rust formatting with a dirty worktree",
                file=sys.stderr,
            )
            return 1, False
        return 0, True

    try:
        jj = subprocess.run(
            [b"jj", b"log", b"--no-graph", b"-r", b"@", b"-T", b"commit_id"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return 0, False
    return 0, jj.returncode == 0 and revision == jj.stdout.rstrip(b"\n")


def main(_arguments: list[str]) -> int:
    if not Path("Cargo.toml").exists():
        return 0
    try:
        updates = parse_updates(sys.stdin.buffer.read())
        status, revision = rust_revision(updates)
        if status or revision is None:
            return status
        status, is_checked_out = checked_out(revision)
        if status:
            return status
        if not is_checked_out:
            print(
                "error: cannot check Rust formatting for a commit that is not checked out",
                file=sys.stderr,
            )
            return 1
        formatted = subprocess.run([b"cargo", b"fmt", b"--check"], check=False)
        return exit_status(formatted.returncode)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: could not run command: {error}", file=sys.stderr)
        return 127
