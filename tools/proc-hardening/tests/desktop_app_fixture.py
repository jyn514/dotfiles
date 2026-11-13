"""Report the app boundary without opening real profiles or desktop services."""
import json
import os
from pathlib import Path
import signal
import stat
import sys

sockets = []
for descriptor in Path("/proc/self/fd").iterdir():
    try:
        if stat.S_ISSOCK(os.fstat(int(descriptor.name)).st_mode):
            sockets.append(descriptor.name)
    except OSError:
        pass
print(json.dumps({
    "argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ),
    "uid": os.getresuid(), "gid": os.getresgid(), "groups": os.getgroups(),
    "sockets": sockets,
    "input": sys.stdin.read() if "--read-stdin" in sys.argv else None,
}), flush=True)
print("fixture diagnostic", file=sys.stderr, flush=True)
if "--wait-file" in sys.argv:
    import time
    target = Path(sys.argv[sys.argv.index("--wait-file") + 1])
    while not target.exists():
        time.sleep(0.01)
if "--signal" in sys.argv:
    os.kill(os.getpid(), signal.SIGTERM)
sys.exit(7 if "--failure" in sys.argv else 0)
