"""Own a session lock in a real process, controlled over pipes by the test."""
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proxy_session import SessionLock

def interrupted(signum, _frame):
    raise SystemExit(128 + signum)

for signum in (signal.SIGINT, signal.SIGTERM):
    signal.signal(signum, interrupted)
print('waiting', flush=True)
assert sys.stdin.readline().strip() == 'acquire'
lock = SessionLock(Path(sys.argv[1]))
try:
    print('shared' if lock.shared else 'new', flush=True)
    for line in sys.stdin:
        command = line.strip()
        if command == 'publish':
            lock.release_coordination()
            print('published', flush=True)
        elif command == 'child':
            child = subprocess.Popen(['sleep', '30'], close_fds=False,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(child.pid, flush=True)
        elif command == 'close':
            break
finally:
    lock.close()
