#!/usr/bin/python3
"""Owned fake native ONLY for local cancellation/process tests, not TicGit semantics."""
import json
import os
from pathlib import Path
import signal
import sys
import time

mode = Path('client_mode').read_text().strip()
if mode == 'block':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
fd = os.open('client_events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (json.dumps({'pid': os.getpid(), 'argv': sys.argv[1:]}) + '\n').encode())
os.close(fd)
if mode == 'block':
    while True:
        time.sleep(1)
if mode == 'delay':
    time.sleep(1.25)
print('local native fixture completed')
if mode == 'delay':
    sys.stdout.write('x' * (2 * 1024 * 1024))
sys.exit(17)
