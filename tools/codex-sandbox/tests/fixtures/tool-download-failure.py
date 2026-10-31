#!/usr/bin/env python3
"""Fail downloads and record any attempt to consume their output."""

import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with Path(os.environ["TOOL_DOWNLOAD_LOG"]).open("a") as log:
    log.write(command + "\n")
sys.exit(64 if command == "curl" else 0)
