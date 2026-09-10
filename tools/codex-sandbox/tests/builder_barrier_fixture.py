"""Two builders must both start before either can finish."""

from pathlib import Path
import os
import sys
import time

root, name, peer = sys.argv[1:]
root = Path(root)
if name.startswith('child-'):
    if os.fork():
        raise SystemExit(0)
    time.sleep(0.2)
(root / name).write_text(str(os.getpid()))
deadline = time.monotonic() + 3
while not (root / peer).exists():
    if time.monotonic() >= deadline:
        raise SystemExit('independent builder was never started')
    time.sleep(0.01)
if name == 'fail':
    raise SystemExit(7)
if name == 'wait':
    time.sleep(60)
print(name)
