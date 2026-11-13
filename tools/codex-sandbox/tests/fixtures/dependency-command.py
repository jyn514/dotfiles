#!/usr/bin/env python3
"""Record disposable dependency-installer commands without installing packages."""
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with Path(os.environ["DEPENDENCY_COMMAND_LOG"]).open("a") as log:
    log.write(json.dumps([command, *sys.argv[1:]]) + "\n")
if command == "patch":
    sys.exit(int(os.environ.get("PATCH_CHECK_STATUS", "0")))
