#!/usr/bin/env python3
"""Native stdio protocol fixture; never accesses real Codex state."""
import json
import os
from pathlib import Path
import sys
import time

assert sys.argv[1:] == ["app-server", "--listen", "stdio://"]
home = Path(os.environ["CODEX_HOME"])
failure = os.environ.get("RENAME_FAILURE")
name = "old title"
(home / "pid").write_text(str(os.getpid()))
try:
    for line in sys.stdin:
        request = json.loads(line)
        with (home / "requests").open("a") as log:
            log.write(line)
        method = request["method"]
        if method == "initialized":
            continue
        if method == "thread/name/set":
            assert request["params"]["threadId"] == "owned-session"
            name = request["params"]["name"]
            if failure == "disconnect":
                break
        result = {}
        if method == "thread/read":
            assert request["params"] == {"threadId": "owned-session", "includeTurns": False}
            result = {"thread": {"name": "stale" if failure == "mismatch" else name}}
        response = {"id": request["id"], "result": result}
        if failure == "read-error" and method == "thread/read":
            response = {"id": request["id"], "error": {"message": "session missing"}}
        print(json.dumps({"method": "thread/name/updated", "params": {}}), flush=True)
        print(json.dumps(response), flush=True)
    if failure == "linger":
        time.sleep(60)
finally:
    (home / "closed").touch()
