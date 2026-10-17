#!/usr/bin/env python3
"""Record the profile helper's fscrypt calls without touching encryption state."""
import json
import os
from pathlib import Path
import sys

with Path(os.environ["FSCRYPT_LOG"]).open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "status":
    print("Unlocked: No" if os.environ["FSCRYPT_LOCKED"] == "1" else "Unlocked: Yes")
