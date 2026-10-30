#!/usr/bin/env python3
"""Delegate fixture queries to native Git, but record rather than rewrite history."""

import json
import os
from pathlib import Path
import subprocess
import sys


arguments = sys.argv[1:]
if arguments[0] in {"revise", "rebase"}:
    status = int(os.environ.get("AUTOSQUASH_EFFECT_STATUS", "0"))
    stdout = stderr = ""
elif arguments[0] in {"symbolic-ref", "for-each-ref", "config", "merge-base"}:
    result = subprocess.run(
        [os.environ["AUTOSQUASH_NATIVE_GIT"], *arguments], capture_output=True
    )
    status = result.returncode
    stdout = os.fsdecode(result.stdout)
    stderr = os.fsdecode(result.stderr)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
else:
    raise SystemExit(f"unexpected Git command: {arguments!r}")
with Path(os.environ["AUTOSQUASH_TRACE"]).open("a") as trace:
    trace.write(json.dumps({"argv": arguments, "status": status,
                            "stdout": stdout, "stderr": stderr}) + "\n")
raise SystemExit(status)
