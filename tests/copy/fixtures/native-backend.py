#!/usr/bin/env python3
"""Record native clipboard invocation without losing argument or stdin boundaries."""

import json
import os
from pathlib import Path
import sys


Path(os.environ["MOCK_ARGUMENTS"]).write_text(
    json.dumps({"backend": Path(sys.argv[0]).name, "argv": sys.argv[1:]})
)
Path(os.environ["MOCK_STDIN"]).write_bytes(sys.stdin.buffer.read())
sys.stdout.buffer.write(b"native output\n\n")
sys.exit(int(os.environ.get("MOCK_STATUS", "0")))
