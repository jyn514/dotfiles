#!/usr/bin/env python3
"""Open path arguments in Dragon."""

import os
import sys


if len(sys.argv) < 2:
    print("usage: dragon.sh PATH...", file=sys.stderr)
    sys.exit(2)

paths = ["./" + value if value.startswith("-") else value for value in sys.argv[1:]]
try:
    os.execvp("dragon", ["dragon", "-x", *paths])
except OSError as error:
    print(f"dragon: {error}", file=sys.stderr)
    sys.exit(127)
