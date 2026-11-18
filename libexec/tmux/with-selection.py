#!/usr/bin/env python3
"""Pass the selected path on stdin as one final argument to COMMAND [ARGS...]."""

import os
import sys


if len(sys.argv) < 2:
    sys.exit("usage: with-selection.py COMMAND [ARGS...]")

selection = sys.stdin.buffer.read()
if not selection:
    sys.exit(0)
if selection.startswith(b"-"):
    selection = b"./" + selection

try:
    os.execvp(sys.argv[1], [*sys.argv[1:], os.fsdecode(selection)])
except OSError as error:
    print(f"{sys.argv[1]}: {error}", file=sys.stderr)
    sys.exit(127)
