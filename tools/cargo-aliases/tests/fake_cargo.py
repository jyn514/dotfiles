"""Deterministic Cargo stand-in for isolated CLI tests."""
import json
import os
from pathlib import Path
import signal
import sys

Path(os.environ["CARGO_CALL_LOG"]).write_text(json.dumps(sys.argv[1:]))
if sys.argv[1:] != ["--list"]:
    raise SystemExit(7)
mode = os.environ.get("CARGO_MODE", "success")
if mode == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
if mode == "invalid-utf8":
    sys.stdout.buffer.write(b"Installed Commands:\n\xff\n")
else:
    sys.stdout.buffer.write("Installed Commands:\n    fancy                alias: run -- café\n".encode("utf-8"))
