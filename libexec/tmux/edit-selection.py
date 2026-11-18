#!/usr/bin/env python3
"""Quote the selection on stdin and type $EDITOR <selection> into this tmux pane."""

import os
import shlex
import sys


selection = sys.stdin.buffer.read()
if not selection:
    sys.exit(0)

try:
    editor = shlex.split(os.environ.get("EDITOR", "vi"))
except ValueError as error:
    print(f"EDITOR: {error}", file=sys.stderr)
    sys.exit(2)
if not editor:
    print("EDITOR is empty", file=sys.stderr)
    sys.exit(2)

command = shlex.join([*editor, os.fsdecode(selection)])
try:
    os.execvp("tmux", [
        "tmux", "send-keys", "C-q", ";",
        "send-keys", "-l", command, ";",
        "send-keys", "C-m",
    ])
except OSError as error:
    print(f"tmux: {error}", file=sys.stderr)
    sys.exit(127)
