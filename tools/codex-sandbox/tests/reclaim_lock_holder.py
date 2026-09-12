"""Simulate a reclaim worker surviving outside a failed service's lifecycle."""

import fcntl
import os
from pathlib import Path
import sys
import time

with (Path('/run/user') / str(os.getuid()) / 'sandbox-reclaim.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    Path(sys.argv[1]).touch()
    time.sleep(60)
