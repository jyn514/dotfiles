#!/usr/bin/env python3
"""Own fixed host-capability TCP listeners for one session."""

import argparse
import os
import signal
import socket
import subprocess
import time


TIC_PORT = 2225
TIC_READY_MESSAGE = 'tic-relay-ready-v1'


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError('port must be between 1 and 65535')
    return number


def wait_listener(port, children):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(child.poll() is not None for child in children):
            raise RuntimeError('listener stopped during startup')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.02)
    raise TimeoutError(f'listener {port} did not become ready')


def serve(host, build_port=None, tic_port=None):
    listeners = []
    if build_port is not None:
        listeners.append((2222, build_port))
    if tic_port is not None:
        listeners.append((TIC_PORT, tic_port))
    if not listeners:
        raise ValueError('at least one listener is required')
    children = []

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    handlers = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for local, remote in listeners:
            children.append(subprocess.Popen([
                '/usr/bin/socat', '-d', '-d', f'TCP4-LISTEN:{local},fork,reuseaddr',
                f'TCP4:{host}:{remote}'], start_new_session=True))
        if tic_port is not None:
            wait_listener(TIC_PORT, children)
            print(TIC_READY_MESSAGE, flush=True)
        # A listener dying leaves an incomplete gateway. Upstream refusal only
        # ends socat's per-connection child; it must not kill the listener.
        pid, status = os.wait()
        child = next(child for child in children if child.pid == pid)
        child.returncode = os.waitstatus_to_exitcode(status)
        return child.returncode or 1
    finally:
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            for child in children:
                # Include forked connection handlers, even if the listener died.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for child in children:
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, choices=('host.lima.internal', 'host.docker.internal'))
    parser.add_argument('--build-port', type=port)
    parser.add_argument('--tic-port', type=port)
    args = parser.parse_args()
    if args.build_port is None and args.tic_port is None:
        parser.error('at least one listener is required')
    return serve(args.host, args.build_port, args.tic_port)


if __name__ == '__main__':
    raise SystemExit(main())
