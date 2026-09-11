#!/usr/bin/env python3
"""Own the fixed host-editor and optional Podman TCP listeners for one session."""

import argparse
import os
import signal
import subprocess


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError('port must be between 1 and 65535')
    return number


def serve(host, editor_port, podman_port=None):
    listeners = [(2223, editor_port)]
    if podman_port is not None:
        listeners.append((2222, podman_port))
    children = []

    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    handlers = {s: signal.signal(s, interrupted) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for local, remote in listeners:
            children.append(subprocess.Popen([
                '/usr/bin/socat', '-d', '-d', f'TCP4-LISTEN:{local},fork,reuseaddr',
                f'TCP4:{host}:{remote}'], start_new_session=True))
        # A listener dying leaves an incomplete gateway. Upstream refusal only
        # ends socat's per-connection child; it must not kill either listener.
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
    parser.add_argument('--editor-port', required=True, type=port)
    parser.add_argument('--podman-port', type=port)
    args = parser.parse_args()
    return serve(args.host, args.editor_port, args.podman_port)


if __name__ == '__main__':
    raise SystemExit(main())
