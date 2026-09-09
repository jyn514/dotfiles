"""Own container waits locally, either on the host or inside Lima."""

import json
import os
import select
import selectors
import signal
import subprocess
import sys
import time
from typing import Any


def monitor(argv, containers, parent_fd=None):
    def stop_agent(reason):
        print(f"sandbox proxies: {reason}; terminating sandbox", file=sys.stderr)
        subprocess.run(
            argv(["rm", "--force", containers[0][1]]), check=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return 1

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if parent_fd is not None and select.select([parent_fd], [], [], 0)[0]:
            if os.read(parent_fd, 1) == b"q":
                return 143
            return stop_agent("supervisor connection stopped")
        result = subprocess.run(
            argv(["inspect", "--format", "{{.State.Running}}", containers[0][1]]),
            text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            break
        time.sleep(0.05)
    else:
        if parent_fd is not None:
            return stop_agent("agent did not start while monitor was waiting")
        raise ValueError("agent container did not start while proxy monitor was waiting")
    waits: list[tuple[str, subprocess.Popen[str]]] = []
    selector = selectors.DefaultSelector()

    def terminate(signum: int, _frame: Any) -> None:
        raise SystemExit(128 + signum)

    signals = (signal.SIGTERM, signal.SIGHUP)
    previous_handlers = {signum: signal.signal(signum, terminate) for signum in signals}
    try:
        if parent_fd is not None:
            selector.register(parent_fd, selectors.EVENT_READ, None)
        for name, container in containers:
            # Only the supervisor watches its parent's pipe; engine children
            # must never compete for either that pipe or the agent's terminal.
            process = subprocess.Popen(
                argv(["wait", container]), text=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            assert process.stdout is not None
            waits.append((name, process))
            selector.register(process.stdout, selectors.EVENT_READ, name)
        ready = selector.select()
        names = {key.data for key, _ in ready}
        if None in names:
            if os.read(parent_fd, 1) == b"q":
                return 143
            names = {"supervisor connection"}
        if "agent" in names:
            return 0
        name = next(iter(names))
        return stop_agent(f"proxy {name} stopped")
    finally:
        # Repeated shutdown requests must not interrupt child reaping.
        for signum in signals:
            signal.signal(signum, signal.SIG_IGN)
        selector.close()
        try:
            for _, process in waits:
                process.terminate()
            deadline = time.monotonic() + 2
            for _, process in waits:
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
            for _, process in waits:
                process.wait(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


if __name__ == "__main__":
    namespace, encoded = sys.argv[1:]
    prefix = ["nerdctl", "--address", "/run/containerd/containerd.sock", "--namespace", namespace]
    raise SystemExit(monitor(lambda arguments: [*prefix, *arguments], json.loads(encoded), parent_fd=0))
