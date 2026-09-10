"""Model a launcher that emits more than a PTY buffer during cleanup."""

import os
from pathlib import Path
import signal
import sys


def cleanup(signum, frame):
    data = b'x' * 262144
    while data:
        data = data[os.write(2, data):]
    Path(sys.argv[1]).touch()
    raise SystemExit(143)


signal.signal(signal.SIGTERM, cleanup)
print('__SANDBOX_PI_READY__', flush=True)
signal.pause()
