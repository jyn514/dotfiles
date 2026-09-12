#!/usr/bin/env python3
"""Configurable image-resolver protocol fixture."""

import json
import os
import signal
import sys
import time


request = json.load(sys.stdin)
mode = os.environ.get("RESOLVER_FIXTURE", "valid")
if mode == "request":
    json.dump(request, sys.stdout)
elif mode == "extra":
    json.dump({"version": 1, "images": {**{name: "sha256:" + "a" * 64 for name in request["images"]}, "extra": "sha256:" + "b" * 64}}, sys.stdout)
elif mode == "duplicate":
    sys.stdout.write('{"version":1,"version":1,"images":{}}')
elif mode == "large":
    sys.stdout.write("x" * (1024 * 1024 + 1))
elif mode == "error":
    print("fixture failed", file=sys.stderr)
    sys.exit(23)
elif mode == "exited-parent":
    if os.fork() == 0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(30)
        os._exit(0)
    json.dump({"version": 1, "images": {name: "sha256:" + "a" * 64 for name in request["images"]}}, sys.stdout)
else:
    json.dump({"version": 1, "images": {name: "sha256:" + "a" * 64 for name in request["images"]}}, sys.stdout)
