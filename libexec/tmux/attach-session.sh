#!/usr/bin/env python3
"""Run source-aware attachment on the explicitly selected tmux server."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The installed entrypoint is a symlink; imports belong beside its real source.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from attachment import main, native_tmux


if __name__ == "__main__":
    arguments = sys.argv[1:]
    # tmux-resurrect invokes the unchanged disable/enable interface from a job.
    if arguments in (["disable"], ["enable"]):
        socket = os.environ.get("TMUX", "").rsplit(",", 2)[0]
        if not socket:
            print("tmux attachment: missing server socket", file=sys.stderr)
            raise SystemExit(1)
        arguments = ["--socket", socket, *arguments]
    raise SystemExit(main(["--tmux", native_tmux(), *arguments]))
