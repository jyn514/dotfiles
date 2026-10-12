#!/usr/bin/env python3
"""Replace live sandboxed Pi commands in a resurrect save with exact resumes."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


@dataclass(frozen=True)
class PiSession:
    pid: int
    session: Path
    cwd: Path

    @classmethod
    def decode(cls, encoded: str) -> PiSession | None:
        value = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4),
                                          altchars=b"-_", validate=True))
        if not isinstance(value, dict) or set(value) != {"version", "pid", "session", "cwd"} \
                or type(value["version"]) is not int or value["version"] != 1 \
                or type(value["pid"]) is not int or value["pid"] <= 1:
            raise ValueError("invalid Pi resurrect registration")
        if value["session"] is None:
            return None
        if not all(isinstance(value[key], str) and Path(value[key]).is_absolute()
                   and not any(char in value[key] for char in "\t\r\n") for key in ("session", "cwd")):
            raise ValueError("invalid Pi resurrect session/cwd")
        return cls(value["pid"], Path(value["session"]), Path(value["cwd"]))


def belongs_to_pane(pid: int, pane_pid: int, parents: dict[int, int]) -> bool:
    seen = set()
    while pid in parents and pid not in seen:
        if pid == pane_pid:
            return True
        seen.add(pid)
        pid = parents[pid]
    return False


def rewrite(snapshot: str, panes: str, parents: dict[int, int]) -> str:
    sessions = {}
    for line in panes.splitlines():
        name, window, index, pane_pid, encoded = line.split("\t", 4)
        if not encoded:
            continue
        try:
            saved = PiSession.decode(encoded)
            if saved is not None and belongs_to_pane(saved.pid, int(pane_pid), parents) \
                    and saved.session.is_file() and saved.cwd.is_dir():
                sessions[name, window, index] = saved
        except (ValueError, OSError) as error:
            print(f"Pi resurrect: skipping {name}:{window}.{index}: {error}", file=sys.stderr)
    result = []
    for line in snapshot.splitlines(keepends=True):
        fields = line.rstrip("\n").split("\t")
        if fields[0] == "pane" and len(fields) == 11:
            saved = sessions.get((fields[1], fields[2], fields[5]))
            if saved is not None:
                # Resurrect reads directory fields with Bash read (without -r).
                fields[7] = ":" + str(saved.cwd).replace("\\", "\\\\").replace(" ", "\\ ")
                fields[10] = ":" + shlex.join(["pi", "--session", str(saved.session),
                                               "--session-dir", str(saved.session.parent)])
                line = "\t".join(fields) + ("\n" if line.endswith("\n") else "")
        result.append(line)
    return "".join(result)


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print("usage: resurrect-pi.py RESURRECT_SAVE", file=sys.stderr)
        return 2
    snapshot = Path(arguments[0])
    try:
        panes = subprocess.run(["tmux", "list-panes", "-a", "-F",
            "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_pid}\t#{@resurrect_pi_session}"],
            check=True, capture_output=True, text=True, timeout=5).stdout
        processes = subprocess.run(["ps", "-e", "-o", "pid=,ppid="], check=True,
                                   capture_output=True, text=True, timeout=5).stdout
        parents = dict(tuple(map(int, line.split())) for line in processes.splitlines())
        original = snapshot.read_text()
        updated = rewrite(original, panes, parents)
        if updated != original:
            # The hook runs before resurrect publishes its `last` symlink.
            # Publish all replacements together; a failed query leaves the save intact.
            with tempfile.NamedTemporaryFile(mode="w", dir=snapshot.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                try:
                    temporary.write(updated)
                    temporary.flush()
                    os.replace(temporary_path, snapshot)
                finally:
                    temporary_path.unlink(missing_ok=True)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Pi resurrect: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
