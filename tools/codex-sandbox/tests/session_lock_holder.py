"""Hold a real sandbox lifetime lock until the test signals cleanup completion."""

import fcntl
from pathlib import Path
import sys

with Path(sys.argv[1]).open("a+b") as lock:
    fcntl.flock(lock, fcntl.LOCK_SH)
    print("ready", flush=True)
    sys.stdin.readline()
print("released", flush=True)
