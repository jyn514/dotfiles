#!/usr/bin/env python3
"""Renumber numeric tmux sessions without colliding with existing names."""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
from collections.abc import Sequence


interrupted_by: int | None = None


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def tmux(*arguments: bytes, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [b"tmux", *arguments],
        check=False,
        stdout=subprocess.PIPE if capture else None,
    )


def unused_prefix(stem: bytes, names: set[bytes], count: int) -> bytes:
    while True:
        candidate = stem + str(os.getpid()).encode() + b"-" + secrets.token_hex(6).encode() + b"-"
        if all(candidate + str(index).encode() not in names for index in range(1, count + 1)):
            return candidate


def rename(old: bytes, new: bytes) -> int:
    return tmux(b"rename-session", b"-t", old, new).returncode


def restore(originals: Sequence[bytes], current: list[bytes], occupied: set[bytes]) -> None:
    """Best-effort two-phase restoration that avoids rollback collisions."""
    changed = [index for index, name in enumerate(current) if name != originals[index]]
    recovery = unused_prefix(b"__renumber-tmux-recovery-", occupied, len(current))

    for index in changed:
        target = recovery + str(index + 1).encode()
        if rename(current[index], target) == 0:
            occupied.discard(current[index])
            occupied.add(target)
            current[index] = target
        else:
            print(
                f"could not move session {os.fsdecode(current[index])!r} aside during rollback",
                file=sys.stderr,
            )

    for index in changed:
        if current[index] == originals[index]:
            continue
        if originals[index] in occupied:
            print(
                f"could not restore session {os.fsdecode(originals[index])!r}: name is occupied",
                file=sys.stderr,
            )
            continue
        if rename(current[index], originals[index]) == 0:
            occupied.discard(current[index])
            occupied.add(originals[index])
            current[index] = originals[index]
        else:
            print(
                f"could not restore session {os.fsdecode(originals[index])!r}",
                file=sys.stderr,
            )


def interrupt(signum: int, _frame: object) -> None:
    global interrupted_by
    interrupted_by = signum


def interruption_status() -> int:
    return 0 if interrupted_by is None else 128 + interrupted_by


def main() -> int:
    listing = tmux(b"list-sessions", b"-F", b"#{session_name}", capture=True)
    if listing.returncode:
        return exit_status(listing.returncode)

    names = listing.stdout.splitlines()
    originals = sorted((name for name in names if name.isdigit()), key=lambda name: (int(name), name))
    if not originals:
        return 0

    occupied = set(names)
    temporary = unused_prefix(b"__renumber-tmux-", occupied, len(originals))
    current = list(originals)
    previous_handlers = {
        signum: signal.signal(signum, interrupt)
        for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    }

    failure = 0
    try:
        for index, old in enumerate(originals):
            new = temporary + str(index + 1).encode()
            status = rename(old, new)
            if status:
                failure = exit_status(status)
                break
            occupied.remove(old)
            occupied.add(new)
            current[index] = new
            if interruption_status():
                failure = interruption_status()
                break

        if not failure:
            for index, old in enumerate(current):
                new = str(index + 1).encode()
                status = rename(old, new)
                if status:
                    failure = exit_status(status)
                    break
                occupied.remove(old)
                occupied.add(new)
                current[index] = new
                if interruption_status():
                    failure = interruption_status()
                    break
    finally:
        if failure:
            for signum in previous_handlers:
                signal.signal(signum, signal.SIG_IGN)
            restore(originals, current, occupied)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    return failure


if __name__ == "__main__":
    raise SystemExit(main())
