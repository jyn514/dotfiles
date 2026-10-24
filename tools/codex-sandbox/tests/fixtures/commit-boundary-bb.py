#!/usr/bin/env python3
"""Run the real bb dispatcher; optionally hold its real file-check result.

The barrier is after actual containment completes, but before the adapter can
consume its reply. No checker status or diagnostic is synthesized.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

root = Path(os.environ["COMMIT_BOUNDARY_TEST_CONTROL"])
dispatcher = os.environ["COMMIT_BOUNDARY_TEST_BB_DISPATCHER"]
arguments = sys.argv[1:]
with (root / "checker-calls.jsonl").open("a") as log:
    log.write(json.dumps({"args": arguments, "pid": os.getpid()}) + "\n")
if arguments != ["agent-split", "--check-file"]:
    os.execv(dispatcher, [dispatcher, *arguments])

child = None


def cancelled(signum, _frame):
    (root / "checker-cancelled.json").write_text(json.dumps({
        "pid": os.getpid(), "signal": signum,
    }))
    raise SystemExit(128 + signum)


signal.signal(signal.SIGTERM, cancelled)
signal.signal(signal.SIGINT, cancelled)
try:
    request = sys.stdin.buffer.read()
    child = subprocess.Popen([dispatcher, *arguments], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = child.communicate(request, timeout=20)
    status = child.returncode
    # Preserve the actual result as independent evidence before the barrier.
    (root / "checker-result.json").write_bytes(stdout)
    (root / "checker-request.json").write_bytes(request)
    (root / "checker-held.json").write_text(json.dumps({
        "pid": os.getpid(), "status": status,
    }))
    deadline = time.monotonic() + 15
    while not (root / "checker-release").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test did not release real checker result")
        time.sleep(0.01)
    sys.stdout.buffer.write(stdout)
    sys.stderr.buffer.write(stderr)
    sys.exit(status)
finally:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
