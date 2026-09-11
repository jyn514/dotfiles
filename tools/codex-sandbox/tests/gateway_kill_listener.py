"""Inject a listener failure inside an owned gateway container."""
from pathlib import Path
import os
import signal

for process in Path('/proc').iterdir():
    if not process.name.isdecimal():
        continue
    try:
        command = (process / 'cmdline').read_bytes().split(b'\0')
        parent = (process / 'stat').read_text().split()[3]
    except FileNotFoundError:
        continue
    if parent == '1' and command[:1] == [b'/usr/bin/socat']:
        os.kill(int(process.name), signal.SIGTERM)
        break
else:
    raise AssertionError('gateway had no supervised listener')
