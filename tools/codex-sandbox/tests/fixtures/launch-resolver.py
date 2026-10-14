#!/usr/bin/env python3
"""Return configured immutable results and record the native resolver request."""
import json
import os
from pathlib import Path
import sys

request = json.load(sys.stdin)
with Path(os.environ["LAUNCH_RESOLVER_REQUEST"]).open("a") as receipt:
    receipt.write(json.dumps(request) + "\n")
json.dump({"version": 1, "images": json.loads(os.environ["LAUNCH_RESOLVER_IMAGES"])}, sys.stdout)
