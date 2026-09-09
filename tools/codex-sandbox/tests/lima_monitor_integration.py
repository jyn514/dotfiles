"""Exercise single-channel supervision with owned disposable containers."""

import argparse
import json
import os
import runpy
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sandbox_runtime import Lima


def wait_for(check):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("monitor did not reach the expected state")


def guest_waits(runtime, containers):
    output = runtime.guest(["ps", "-eo", "pid,ppid,args"], capture_output=True, text=True).stdout
    return [line.split(None, 2) for line in output.splitlines()
            if any(f" wait {container}" in line for _, container in containers)
            and "nerdctl --address" in line]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path.home() / ".local/state/codex-sandbox-lima")
    parser.add_argument("--image", help="already local image containing sleep")
    parser.add_argument("--monitor", help=argparse.SUPPRESS)
    args = parser.parse_args()
    runtime = Lima(args.state)
    if args.monitor:
        return runtime.monitor(json.loads(args.monitor))
    if not args.image:
        parser.error("--image is required")
    launcher = runpy.run_path(str(Path(__file__).resolve().parents[1] / "codex-sandbox"))
    image = runtime.resolve_image(args.image)
    name = "sandbox-monitor-test-" + uuid.uuid4().hex[:12] + "-not-started"
    state = SimpleNamespace()

    def lose_monitor_before_start():
        inspected = runtime.run(["inspect", "--format", "{{.State.Running}}", name], capture_output=True)
        assert inspected.stdout.strip() == "false", "monitor started before container creation"
        state.monitor_process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                                  "--state", str(args.state), "--monitor", json.dumps([("agent", name)])],
                                                 stdin=subprocess.DEVNULL)
        state.monitor_process.kill()
        state.monitor_process.wait()

    print("EXPECT: stopping startup supervision may produce a nerdctl transport error", flush=True)
    try:
        with runtime.workload(image, name, ["--network", "none", "--entrypoint", "sleep"], ["300"],
                              before_start=lose_monitor_before_start) as process:
            state.agent_process = process
            launcher["wait_for_monitored_agent"](state)
        raise AssertionError("lost startup monitor was ignored")
    except launcher["LauncherError"]:
        assert runtime.run(["inspect", name], check=False, capture_output=True).returncode != 0
    print("PASS: supervisor lost before agent start; owned workload removed", flush=True)
    for outcome in ("agent", "proxy", "cancel", "lost-supervisor", "lost-channel"):
        prefix = "sandbox-monitor-test-" + uuid.uuid4().hex[:12]
        containers = [(name, prefix + "-" + name) for name in ("agent", "auth", "jj", "zulip")]
        process = None
        try:
            for _, container in containers:
                runtime.run(["run", "--detach", "--pull=never", "--name", container,
                             "--network", "none", "--entrypoint", "sleep", args.image, "300"],
                            stdout=subprocess.DEVNULL)
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                        "--state", str(args.state), "--monitor", json.dumps(containers)],
                                       stdin=subprocess.DEVNULL)
            wait_for(lambda: len(guest_waits(runtime, containers)) == 4)
            assert len({row[1] for row in guest_waits(runtime, containers)}) == 1, "waits have different guest supervisors"
            if outcome in ("agent", "proxy"):
                runtime.terminate(containers[0 if outcome == "agent" else 1][1])
            elif outcome == "lost-channel":
                print("EXPECT: the owned SSH client will report SIGKILL", flush=True)
                rows = subprocess.run(["ps", "-axo", "pid,ppid,comm"], check=True,
                                      capture_output=True, text=True).stdout.splitlines()[1:]
                children = {process.pid}
                while True:
                    descendants = {int(row.split(None, 2)[0]) for row in rows
                                   if int(row.split(None, 2)[1]) in children}
                    if descendants <= children:
                        break
                    children |= descendants
                transports = [int(row.split(None, 2)[0]) for row in rows
                              if int(row.split(None, 2)[0]) in children
                              and Path(row.split(None, 2)[2]).name == "ssh"]
                assert len(transports) == 1, transports
                os.kill(transports[0], signal.SIGKILL)
            else:
                process.send_signal(signal.SIGTERM if outcome == "cancel" else signal.SIGKILL)
            status = process.wait(timeout=15)
            if outcome == "lost-channel":
                assert status != 0
            else:
                assert status == {"agent": 0, "proxy": 1, "cancel": 143, "lost-supervisor": -9}[outcome], status
            wait_for(lambda: not guest_waits(runtime, containers))
            if outcome == "lost-supervisor":
                wait_for(lambda: runtime.run(["inspect", containers[0][1]], check=False,
                                             capture_output=True).returncode != 0)
            observed = runtime.run(["inspect", "--format", "{{.State.Running}}", containers[0][1]],
                                   check=False, capture_output=True)
            assert (observed.returncode == 0 and observed.stdout.strip() == "true") == (outcome == "cancel")
            print(f"PASS: {outcome}; four local waits reaped", flush=True)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            for _, container in containers:
                runtime.run(["rm", "--force", container], capture_output=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
