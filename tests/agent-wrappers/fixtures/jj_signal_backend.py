#!/usr/bin/env python3
"""Owned recording backend that pauses in a selected native lifecycle phase."""
import json
import os
from pathlib import Path
import signal
import sys

record = Path(os.environ['JJ_SIGNAL_RECORD'])
with record.open('a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\n')
count = len(record.read_text().splitlines())
phase = os.environ['JJ_SIGNAL_PHASE']
if count == {'pre': 1, 'main': 2, 'post': 3}[phase]:
    if os.environ.get('JJ_SIGNAL_EXIT_ZERO'):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    Path(os.environ['JJ_SIGNAL_READY']).write_text(str(os.getpid()))
    signal.pause()
