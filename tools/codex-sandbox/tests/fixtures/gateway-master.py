"""Lifecycle stand-in; OpenSSH itself resolves the production master arguments."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

settings = dict(line.split(' ', 1) for line in subprocess.check_output(
    ['/usr/bin/ssh', '-G', *sys.argv[1:]], text=True,
).splitlines())
with socket.socket(socket.AF_UNIX) as server:
    Path(os.environ['MASTER_RECORD']).write_text(json.dumps({
        'pid': os.getpid(), 'settings': settings,
    }))
    server.bind(settings['controlpath'])
    server.listen()
    while True:
        signal.pause()
