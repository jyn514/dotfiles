"""Private fixed-destination TicGit guest relay; not an application protocol."""
from __future__ import annotations

import argparse
import signal
import socket
import sys
import threading
import time

from host_tcp_bridge import FixedTcpBridge

# Imported by the launcher: the relay has no request-selected listen address.
PORT = 2225


def probe() -> int:
    """Bounded TCP-listen check only. Authenticated help checks the full path."""
    deadline = time.monotonic() + 5
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=min(0.2, remaining)):
                return 0
        except OSError:
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    print("tic relay: listener probe exceeded five seconds", file=sys.stderr)
    return 125


def serve(target: tuple[str, int]) -> int:
    stopped = threading.Event()
    previous = {}
    bridge = FixedTcpBridge(target, listen_address=("0.0.0.0", PORT),
                            allow_all_peers=True, max_connections=16)
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, lambda _signum, _frame: stopped.set())
        bridge.start()
        while not stopped.wait(0.2):
            if bridge.thread is None or not bridge.thread.is_alive():
                raise RuntimeError("listener stopped unexpectedly")
        return 0
    except (OSError, RuntimeError) as error:
        print(f"tic relay: {error}", file=sys.stderr)
        return 125
    finally:
        bridge.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--target-host")
    parser.add_argument("--target-port", type=int)
    args = parser.parse_args(argv)
    if args.probe:
        if args.target_host is not None or args.target_port is not None:
            parser.error("--probe does not accept a target")
        return probe()
    if not args.target_host or args.target_port is None or not 1 <= args.target_port <= 65535:
        parser.error("serve requires --target-host and --target-port (1..65535)")
    return serve((args.target_host, args.target_port))


if __name__ == "__main__":
    raise SystemExit(main())
