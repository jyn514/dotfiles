"""Session-owned listeners on Lima's existing OpenSSH control master."""

import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys

from lima.proxy_socket import directory, private
from sandbox_runtime import RuntimeError


def local_path(owner):
    return directory(owner) / 'host'


def control(runtime, owner, operation):
    config = Path(runtime.record['socket']).parent.parent / 'ssh.config'
    # ControlMaster=no forbids creating an unowned master if Lima's is gone.
    return subprocess.run([
        '/usr/bin/ssh', '-F', str(config), '-o', 'ControlMaster=no',
        '-O', operation, '-L', f'{local_path(owner)}:{directory(owner) / "s"}',
        'lima-' + runtime.record['instance'],
    ], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)


def guest_alias(runtime, operation, record):
    command = runtime.host.guest_argv(runtime.record, 'python3', '-',
                                     operation, record['owner'], record['target'])
    command[0] = '/usr/bin/ssh'
    subprocess.run(command, input=Path(__file__).with_name('proxy_socket.py').read_bytes(),
                   capture_output=True, check=True, timeout=10)


def start(runtime, record):
    owner = record['owner']
    path = directory(owner)
    path.mkdir(mode=0o700)
    private(path)
    guest_alias(runtime, 'create', record)
    result = control(runtime, owner, 'forward')
    if result.returncode:
        raise RuntimeError('proxy socket forwarding failed: ' + result.stderr.strip())
    if not stat.S_ISSOCK(local_path(owner).lstat().st_mode):
        raise RuntimeError('SSH did not publish the proxy socket')


def stop(runtime, record):
    owner = record['owner']
    path = directory(owner)
    if path.exists() or path.is_symlink():
        private(path)
        local = local_path(owner)
        if local.exists() or local.is_symlink():
            if not stat.S_ISSOCK(local.lstat().st_mode):
                raise RuntimeError('proxy listener was replaced')
            result = control(runtime, owner, 'cancel')
            if result.returncode:
                # A replacement master knows nothing of the old listener.
                # Its stale inode is removable only if it refuses connections.
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                    stream.settimeout(5)
                    try:
                        stream.connect(str(local))
                    except (ConnectionRefusedError, FileNotFoundError):
                        pass
                    else:
                        raise RuntimeError('proxy socket cancellation failed: ' + result.stderr.strip())
            local.unlink(missing_ok=True)
        path.rmdir()
    guest_alias(runtime, 'remove', record)


def check(owner):
    private(directory(owner))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(5)
        stream.connect(str(local_path(owner)))


def forward(owner):
    private(directory(owner))
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    handlers = {signum: signal.signal(signum, interrupted) for signum in signals}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.connect(str(local_path(owner)))
            while chunk := os.read(sys.stdin.fileno(), 65536):
                stream.sendall(chunk)
            stream.shutdown(socket.SHUT_WR)
            while chunk := stream.recv(65536):
                sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        return 0
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
