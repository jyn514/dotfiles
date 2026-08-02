#!/usr/bin/env python3
"""Select an existing detached tmux session after a session is created."""

from __future__ import annotations

import subprocess
import sys


DISABLE_OPTION = "@attach-session-disable"


def run_tmux(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["tmux", *arguments],
        check=False,
        stdout=subprocess.PIPE if capture else None,
    )


def query(*arguments: str) -> bytes:
    result = run_tmux(*arguments, capture=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    return result.stdout.rstrip(b"\n")


def main(arguments: list[str]) -> int:
    if arguments == ["disable"]:
        return run_tmux("set-option", "-s", DISABLE_OPTION, "1").returncode
    if arguments == ["enable"]:
        return run_tmux("set-option", "-su", DISABLE_OPTION).returncode

    # tmux-resurrect brackets its restore with the modes above. An unset option
    # is reported as a failed query, so only a successful query disables work.
    disabled = subprocess.run(
        ["tmux", "show-option", "-sv", DISABLE_OPTION],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if disabled.returncode == 0:
        return 0

    # An explicit switch from another session makes the new empty session
    # intentional. A detached current session was likely created by a script.
    if query("display-message", "-p", "#{client_last_session}"):
        return 0
    if query("display-message", "-p", "#{session_attached}") == b"0":
        return 0

    output = query(
        "list-sessions", "-f", "#{?session_attached,0,1}", "-F", "#{session_id}"
    )
    sessions = output.splitlines()
    if not sessions:
        return 0

    result = run_tmux("set-option", "destroy-unattached")
    if result.returncode:
        return result.returncode
    return run_tmux("switch-client", "-t", sessions[0].decode("ascii")).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
