"""Emit exact fixture bytes; wait until each fragment reaches the reader."""
import base64
import json
from pathlib import Path
import sys
import time

params = json.loads(sys.stdin.readline())["params"]
stream = sys.stderr.buffer if params.get("stderr") else sys.stdout.buffer
for index, chunk in enumerate(params["chunks"]):
    stream.write(base64.b64decode(chunk))
    stream.flush()
    if index < len(params["chunks"]) - 1:
        release = Path(params["release"]) / str(index)
        deadline = time.monotonic() + 5
        while not release.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("fragment acknowledgement timed out")
            time.sleep(0.001)
sys.exit(params.get("status", 0))
