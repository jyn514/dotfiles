"""Hold a test transport open and return its complete metadata request."""
import json
import os
from pathlib import Path
import sys
import time

request = json.loads(sys.stdin.readline())
directory = Path(os.environ["CODEX_GUEST_CALL_TEST_DIR"])
if request["params"].get("command") == "pause":
    (directory / "started").touch()
    while not (directory / "release").exists():
        time.sleep(0.01)
print(json.dumps({"kind": "result", "result": request}), flush=True)
