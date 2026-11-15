#!/usr/bin/env python3
"""Record artifact selection and reject its checksum before extraction."""

import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with Path(os.environ["TOOL_DOWNLOAD_LOG"]).open("a") as log:
    log.write(json.dumps([command, *sys.argv[1:]]) + "\n")
if command == "uname":
    print(os.environ["TOOL_TEST_ARCH"])
sys.exit(64 if command == "sha256sum" else 0)
