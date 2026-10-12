#!/usr/bin/env python3
"""External validator/launcher receipt for the owned host-Pi handoff test."""

import json
import os
from pathlib import Path
import sys

if sys.argv[1:2] == ["validate-cd"]:
    destination = str(Path(sys.argv[2]).resolve(strict=True))
    print(json.dumps({"destination": destination, "repository": destination}))
else:
    Path(os.environ["HOST_PI_HANDOFF_RECEIPT"]).write_text(json.dumps({
        "cwd": os.getcwd(),
        "previous_cwd": os.environ.get("CODEX_SANDBOX_PREVIOUS_CWD"),
        "arguments": sys.argv[1:],
    }))
