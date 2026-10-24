#!/usr/bin/python3
"""Owned fake native for process-bound tests ONLY; semantic tests use pinned ti."""
import json
import os
from pathlib import Path
import signal
import sys
import time

mode = Path('fixture-mode').read_text().strip()
Path('fixture-started').write_text(str(os.getpid()))
with Path('fixture-pids').open('a') as stream:
    stream.write(str(os.getpid()) + '\n')
if mode == 'environment':
    data = sys.stdin.buffer.read()
    print(json.dumps({'argv': sys.argv[1:], 'stdin': data.decode(), 'env': dict(os.environ), 'cwd': os.getcwd()}))
elif mode == 'sleep':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
elif mode == 'output':
    while True:
        sys.stdout.buffer.write(b'x' * 65536)
        sys.stdout.buffer.flush()
elif mode == 'stderr':
    while True:
        sys.stderr.buffer.write(b'x' * 65536)
        sys.stderr.buffer.flush()
elif mode == 'maximum':
    sys.stdout.buffer.write(b'x' * (4 * 1024 * 1024))
elif mode == 'invalid-utf8':
    sys.stdout.buffer.write(b'\xff')
elif mode == 'exit':
    print('native stdout')
    print('native stderr', file=sys.stderr)
    sys.exit(17)
else:
    raise AssertionError(mode)
