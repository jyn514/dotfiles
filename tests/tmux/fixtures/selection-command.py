#!/usr/bin/env python3
"""Record a selection action without opening applications or user state."""

import json
import os
from pathlib import Path
import sys


Path(os.environ["ACTION_CALLS"]).write_text(json.dumps(sys.argv[1:]))
if "ACTION_COMMAND" in os.environ:
    Path(os.environ["ACTION_COMMAND"]).write_text(Path(sys.argv[0]).name)
if "ACTION_STDIN" in os.environ:
    Path(os.environ["ACTION_STDIN"]).write_bytes(sys.stdin.buffer.read())
sys.exit(int(os.environ.get("ACTION_STATUS", "0")))
