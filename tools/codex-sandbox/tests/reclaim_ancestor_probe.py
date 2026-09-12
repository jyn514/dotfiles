"""Diagnostic-only reclaim target, never installed in production."""

import errno
from pathlib import Path
import sys

try:
    Path(sys.argv[1], 'memory.reclaim').write_text('33554432')
except OSError as error:
    if error.errno != errno.EAGAIN:
        raise
