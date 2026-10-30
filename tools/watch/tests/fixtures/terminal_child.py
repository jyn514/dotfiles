"""A disposable command recording real terminal input and interrupts."""
import json
import os
from pathlib import Path
import signal
import sys
import time

log = Path(sys.argv[1])


def record(event: str, **values: object) -> None:
    with log.open("a") as stream:
        stream.write(json.dumps({"event": event, "pid": os.getpid(), "pgid": os.getpgrp(), **values}) + "\n")


def interrupt(number: int, frame: object) -> None:
    record("SIGINT")
    os._exit(130)


if sys.argv[2] != "final-output":
    signal.signal(signal.SIGINT, interrupt)
record("start")
print("child started", flush=True)
if sys.argv[2] == "interval":
    record("done")
else:
    record("input", text=os.read(0, 4096).decode())
    try:
        time.sleep(60)
    finally:
        if sys.argv[2] == "final-output":
            record("SIGINT-cleanup")
            sys.stdout.buffer.write(b"x" * 1048576)
            sys.stdout.buffer.flush()
            record("output-complete")
