#!/usr/bin/env python3
"""Expose a newly spawned Dashboard TUI in the most recently used Pi session.

This runs before the launcher: the new Pi must not participate in choosing its
own destination. Dashboard retains its backing window and all process ownership.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys


@dataclass(frozen=True)
class Process:
    parent: int
    group: int
    foreground: int
    tty: str
    state: str


def process_table(text: str) -> dict[int, Process]:
    result = {}
    for line in text.splitlines():
        pid, parent, group, foreground, tty, state = line.split()
        result[int(pid)] = Process(int(parent), int(group), int(foreground), tty, state)
    return result


def registered_pid(encoded: str) -> int:
    # session-side.ts publishes this schema even before a session file exists.
    # Unlike resurrect, placement needs a live UI, not a persisted conversation.
    value = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4),
                                       altchars=b"-_", validate=True))
    if not isinstance(value, dict) or set(value) != {"version", "pid", "session", "cwd"} \
            or type(value["version"]) is not int or value["version"] != 1 \
            or type(value["pid"]) is not int or value["pid"] <= 1:
        raise ValueError("invalid Pi resurrect registration")
    for key in ("cwd", "session"):
        path = value[key]
        if key == "session" and path is None:
            continue
        if not isinstance(path, str) or not Path(path).is_absolute() \
                or any(char in path for char in "\t\r\n"):
            raise ValueError("invalid Pi resurrect path")
    return value["pid"]


def foreground_pi(encoded: str, pane_pid: int, pane_tty: str,
                  processes: dict[int, Process]) -> bool:
    try:
        pid = registered_pid(encoded)
    except (ValueError, TypeError):
        return False
    process = processes.get(pid)
    if process is None or process.state.startswith(("Z", "X", "T", "t")) \
            or process.tty != pane_tty.removeprefix("/dev/") \
            or process.group <= 0 or process.group != process.foreground:
        return False
    # host_pi_owner is detached (setsid), NOT a terminal ancestor. The retained
    # pane frontend execs sandbox-host-pi, whose Pi child inherits its foreground
    # process group/controlling TTY. Follow that UI lineage, never the owner.
    seen = set()
    while pid in processes and pid not in seen:
        if pid == pane_pid:
            return True
        seen.add(pid)
        pid = processes[pid].parent
    return False


def place(environment: dict[str, str]) -> None:
    pane = environment.get("TMUX_PANE", "")
    context = environment.get("TMUX", "").rsplit(",", 2)
    if not environment.get("PI_DASHBOARD_SPAWN_TOKEN") or len(context) != 3 \
            or not context[0] or not re.fullmatch(r"%\d+", pane):
        return

    def tmux(*arguments: str) -> str:
        # Pin every query/mutation to the source server, not tmux's default
        # socket or an unrelated server selected by the caller's environment.
        return subprocess.run(["tmux", "-S", context[0], *arguments], check=True,
                              capture_output=True, text=True, timeout=5).stdout.rstrip("\n")

    rows = tmux("list-panes", "-a", "-F",
        "#{session_id}|#{==:#{session_name},pi-dashboard}|#{session_activity}|#{window_id}|"
        "#{pane_id}|#{pane_pid}|#{pane_tty}|#{@resurrect_pi_session}")
    panes = [line.split("|", 7) for line in rows.splitlines()]
    source = next((row for row in panes if len(row) == 8
                   and row[1] == "1" and row[4] == pane), None)
    if source is None:
        return
    # Descendant CLI invocations inherit Dashboard's bridge token too. Retain
    # it for bridge registration, but only place this pane once, at first entry.
    if tmux("show-option", "-pqv", "-t", pane, "@dotfiles_dashboard_placed"):
        return
    tmux("set-option", "-p", "-t", pane, "@dotfiles_dashboard_placed", "1")
    processes = process_table(subprocess.run(
        ["ps", "-ax", "-o", "pid=,ppid=,pgid=,tpgid=,tty=,stat="],
        check=True, capture_output=True, text=True, timeout=5).stdout)
    eligible = set()
    for row in panes:
        if len(row) != 8:
            continue
        session, backing, activity, window, _, pid, tty, encoded = row
        if backing == "1" or window == source[3] or not encoded:
            continue
        if foreground_pi(encoded, int(pid), tty, processes):
            eligible.add((int(activity), session))
    if eligible:
        _, destination = max(eligible)
        # IDs avoid tmux's name-prefix matching. -d leaves all selections alone;
        # link-window shares the original window/panes rather than moving them.
        tmux("link-window", "-d", "-s", source[3], "-t", destination + ":")


def main() -> int:
    try:
        place(dict(os.environ))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Placement is cosmetic; a disappearing candidate must not prevent the
        # authoritative launcher/bridge from starting in Dashboard's window.
        print(f"Pi Dashboard window placement skipped: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
