"""Observe/delay terminal replies around the real connector, never replace the checker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(os.environ["COMMIT_BOUNDARY_TEST_CONTROL"])
request = sys.stdin.buffer.readline()
parsed = json.loads(request)
with (root / "requests.jsonl").open("ab") as log:
    log.write(request)
control_file = root / "control.json"
control = json.loads(control_file.read_text()) if control_file.exists() else {}
connector = Path(__file__).with_name("local-tool-connect.py")
# Keep stdin open until the worker's terminal reply, exactly as callGuest does.
# Closing it immediately half-closes the real socket and cancels asynchronous tools.
child = subprocess.Popen([sys.executable, str(connector)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
child.stdin.write(request)
child.stdin.flush()
frames = []
while True:
    line = child.stdout.readline()
    if not line:
        break
    frames.append(line)
    if json.loads(line).get("kind") in ("result", "error"):
        break
child.stdin.close()
stdout = b"".join(frames) + child.stdout.read()
stderr = child.stderr.read()
status = child.wait()
with (root / "replies.jsonl").open("ab") as log:
    log.write(stdout)
if parsed.get("params", {}).get("path") == control.get("path"):
    if control.get("hold"):
        (root / "held").touch()
        deadline = time.monotonic() + 15
        while not (root / "release").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("test did not release terminal reply")
            time.sleep(0.01)
    if control.get("drop"):
        sys.stderr.write("deliberately lost terminal reply\n")
        sys.exit(7)
sys.stdout.buffer.write(stdout)
sys.stderr.buffer.write(stderr)
sys.exit(status)
