#!/usr/bin/env python3
"""Open a Google search for the selection on stdin."""

import os
import sys
from urllib.parse import urlencode


selection = sys.stdin.buffer.read()
if not selection:
    sys.exit(0)

url = "https://www.google.com/search?" + urlencode({b"q": selection})
try:
    os.execvp("open", ["open", url])
except OSError as error:
    print(f"open: {error}", file=sys.stderr)
    sys.exit(127)
