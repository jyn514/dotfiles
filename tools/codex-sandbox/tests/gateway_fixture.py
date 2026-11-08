"""Owned local production gateway, not a VM or host-forwarding substitute.

Uses production fixed listener ports; refuses to adopt an existing listener.
Only the provider's host-name mapping and container process are replaced.
"""
import fcntl
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys

SANDBOX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SANDBOX))
from gateway import TIC_PORT, TIC_READY_MESSAGE, wait_listener


class LocalGateway:
    def __init__(self, tic_port, build_port=None):
        self.port = TIC_PORT if tic_port is not None else 2222
        self.process = None
        # Native suites run concurrently by file. Serialize only these owned
        # fixed-port fixtures, not unrelated tests or any provider resources.
        lock = SANDBOX.parents[1] / 'work/cache/tests/gateway.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock = lock.open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX)
            for port in (([TIC_PORT] if tic_port is not None else [])
                         + ([2222] if build_port is not None else [])):
                with socket.socket() as reservation:
                    reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    reservation.bind(('127.0.0.1', port))
            self.process = subprocess.Popen(
                [sys.executable, str(Path(__file__)), str(tic_port) if tic_port is not None else '-',
                 *([str(build_port)] if build_port is not None else [])],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True)
            if tic_port is None:
                wait_listener(2222, [self.process])
            else:
                if not select.select([self.process.stdout], [], [], 7)[0]:
                    raise RuntimeError('owned gateway readiness timed out')
                if self.process.stdout.readline().decode().strip() != TIC_READY_MESSAGE:
                    raise RuntimeError('owned gateway failed readiness')
        except BaseException:
            self.stop()
            raise

    def stop(self):
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait(timeout=3)
                self.process.stdout.close()
        finally:
            self.lock.close()


if __name__ == '__main__':
    from gateway import serve
    raise SystemExit(serve('127.0.0.1', tic_port=int(sys.argv[1]) if sys.argv[1] != '-' else None,
                          build_port=int(sys.argv[2]) if len(sys.argv) > 2 else None))
