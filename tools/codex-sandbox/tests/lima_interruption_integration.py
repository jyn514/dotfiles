#!/usr/bin/env python3
"""Interrupt the real disposable Lima fixture and verify its VM is removed."""

import ast
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time


FIXTURE = Path(__file__).with_name("lima_network_integration.py")


def interrupt(phase):
    events = queue.Queue()
    instance = None
    process = subprocess.Popen([sys.executable, str(FIXTURE)], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)

    def read():
        for line in process.stdout:
            print(line, end="", flush=True)
            events.put(line)
        events.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 600
        while True:
            line = events.get(timeout=max(0.01, deadline - time.monotonic()))
            if line is None:
                raise AssertionError("fixture exited before interruption checkpoint")
            if line.startswith("Owned fixture: "):
                instance = line.strip().removeprefix("Owned fixture: ")
                if not re.fullmatch(r"sandbox-network-fixture-[0-9a-f]{12}", instance):
                    instance = None
                    raise AssertionError("invalid owned fixture identity")
            if not line.startswith("+ "):
                continue
            argv = ast.literal_eval(line[2:])
            at_start = argv[:2] == ("limactl", "start")
            at_probe = argv[:2] == ("limactl", "shell") and "/usr/local/share/codex-sandbox/fixture/probe.py" in argv
            if (phase == "start" and at_start) or (phase == "probe" and at_probe):
                # The command announcement precedes Popen. Require its live
                # direct child; a scheduling delay must not pass this test.
                child_deadline = time.monotonic() + 10
                while True:
                    listing = subprocess.run(["ps", "-axo", "pid=,ppid=,command="],
                                             capture_output=True, text=True, check=True, timeout=5)
                    children = [row.split(None, 2) for row in listing.stdout.splitlines()]
                    if any(len(row) == 3 and row[1] == str(process.pid)
                           and "limactl " + argv[1] in row[2] and instance in row[2]
                           and (phase != "probe" or "/fixture/probe.py" in row[2])
                           for row in children):
                        break
                    if time.monotonic() >= child_deadline or process.poll() is not None:
                        raise AssertionError("announced phase never acquired a live child")
                    time.sleep(0.05)
                process.send_signal(signal.SIGTERM)
                break
        if process.wait(timeout=60) != 128 + signal.SIGTERM:
            raise AssertionError("fixture did not preserve its interruption status")
        result = subprocess.run(["limactl", "list", "--quiet"],
                                capture_output=True, text=True, check=True, timeout=30)
        if instance is None or instance in result.stdout.splitlines():
            raise AssertionError("interrupted fixture did not remove its owned VM")
        print(f"Interruption during {phase}: status preserved; owned VM removed.", flush=True)
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                print(f"Fixture cleanup timed out; inspect owned instance {instance}", file=sys.stderr)
        if instance is not None:
            # Preserve the test failure, but independently reclaim its owned VM
            # if the interrupted launcher failed to do so.
            remaining = subprocess.run(["limactl", "list", "--quiet"], capture_output=True,
                                       text=True, check=True, timeout=30).stdout.splitlines()
            if instance in remaining:
                subprocess.run(["limactl", "delete", "--force", "--tty=false", instance],
                               check=True, timeout=60)
        reader.join(timeout=5)
        if not reader.is_alive():
            process.stdout.close()


if __name__ == "__main__":
    for phase in ("start", "probe"):
        interrupt(phase)
