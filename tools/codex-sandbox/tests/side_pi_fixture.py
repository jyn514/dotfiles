#!/usr/bin/env python3
"""Local worker/connector adapter; never a fake Pi or a container substitute."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from host_pi_owner import HostPiOwner, detached_frontend, send


def publish(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def owner_main(arguments, bootstrap):
    runtime = Path(arguments[0])
    config = json.loads((runtime / "config.json").read_text())
    environment = dict(os.environ)
    environment.update(CODEX_SANDBOX_TOOL_CONNECT=str(Path(__file__).resolve()),
                       CODEX_SANDBOX_TOOL_CONTAINER="local-test-worker-not-container",
                       CODEX_SANDBOX_TOOL_SOCKET=str(runtime / "worker.sock"),
                       CODEX_SANDBOX_GUEST_CWD=config["guest_cwd"],
                       CODEX_SANDBOX_PI_TOOL_MODULE=config["tool_module"])
    # Deliberately shared legacy publication across source, side and worker.
    # Per-call attribution must win even after B overwrites this file while A waits.
    environment.update(config.get("identity_environment", {}))
    environment["SIDE_PI_RUNTIME"] = str(runtime)
    worker = None
    owner = None
    stopped = threading.Event()
    receipt = {"owner_pid": os.getpid(), "tmux": environment["TMUX"],
               "source_pane": environment["TMUX_PANE"],
               "guest_cwd": config["guest_cwd"], "host_cwd": os.getcwd()}
    succeeded = False
    with (runtime / "worker.log").open("w") as log:
        try:
            worker = subprocess.Popen(["node", str(ROOT / "image/tool-worker.mjs")],
                                      cwd=config["guest_cwd"], env=environment,
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            receipt["worker_pid"] = worker.pid
            publish(runtime / "receipt.json", receipt)
            deadline = time.monotonic() + 10
            while not (runtime / "worker.sock").exists():
                if worker.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("local real tool-worker failed to start")
                time.sleep(.05)
            owner = HostPiOwner(ROOT / "sandbox-host-pi", config["arguments"],
                                os.getcwd(), environment, timeout=15)
            owner.original.pane = environment["TMUX_PANE"]
            owner.mark_bootstrapped()
            owner.start()

            def monitor():
                while not stopped.is_set():
                    with owner.lock:
                        receipt["attachments"] = [
                            {"session": str(item.session) if item.session else None,
                             "pane": item.pane, "ready": item.ready}
                            for item in owner.attachments.values()]
                    publish(runtime / "receipt.json", receipt)
                    stopped.wait(.05)

            threading.Thread(target=monitor, daemon=True).start()
            # Used only for bounded emergency teardown by the integration runner.
            signal.signal(signal.SIGTERM, lambda *_: worker.terminate())
            send(bootstrap, owner.launch_spec(owner.original))
            owner.wait(worker)
            succeeded = True
        finally:
            stopped.set()
            if worker is not None:
                if worker.poll() is None:
                    worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
            publish(runtime / "cleanup.json", {"worker_pid": worker.pid if worker else None,
                                                "worker_status": worker.returncode if worker else None,
                                                "succeeded": succeeded})
            if owner is not None:
                owner.finish(succeeded)
    return 0 if succeeded else 1


def consumer(label, pause=False, legacy=False):
    runtime = Path(os.environ["SIDE_PI_RUNTIME"])
    publish(runtime / f"{label}.started.json", {"call_model": os.environ.get("PI_CALL_MODEL"),
                                              "legacy": json.loads(Path(os.environ["PI_MODEL_FILE"]).read_text())})
    if pause:
        deadline = time.monotonic() + 20
        while not (runtime / f"{label}.release").exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("bounded attribution pause expired")
            time.sleep(.05)
    environment = dict(os.environ)
    if legacy:
        # Disposable counterfactual: reproduce the old consumer without modifying
        # its parser or any production source. Only this subprocess loses the field.
        environment.pop("PI_CALL_MODEL", None)
    wrapper = ROOT.parents[1] / "libexec/agent-wrappers/jj"
    return subprocess.call([str(wrapper), "status", label], env=environment)


def jj_real(label):
    runtime = Path(os.environ["SIDE_PI_RUNTIME"])
    result = {"label": label, "jj_user": os.environ.get("JJ_USER"),
              "call_model": os.environ.get("PI_CALL_MODEL"),
              "legacy": json.loads(Path(os.environ["PI_MODEL_FILE"]).read_text()),
              "cwd": os.getcwd()}
    publish(runtime / f"{label}.jj.json", result)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["owner"]:
        raise SystemExit(detached_frontend(sys.argv[2:], owner_main))
    if sys.argv[1:2] == ["consumer"]:
        raise SystemExit(consumer(sys.argv[2], "--pause" in sys.argv, "--legacy" in sys.argv))
    if sys.argv[1:2] == ["jj-real"]:
        raise SystemExit(jj_real(sys.argv[-1]))
    if sys.argv[1:2] == ["--"]:
        # Read-only routing fixture: actual wrapper decides and stamps identity.
        print(json.dumps({"backend": "native", "workspace": None, "destination": None,
                          "command": sys.argv[2:], "hooks": False}))
        raise SystemExit(0)
    # Record, but do not alter, the production producer's request before forwarding
    # it through the actual image connector and worker. No shared model state here.
    if len(sys.argv) != 1:
        raise SystemExit("expected owner, consumer, jj-real, route, or connector stdin")
    limit = 8 * 1024 * 1024 + 1
    incoming = bytearray()
    while b"\n" not in incoming and len(incoming) < limit:
        chunk = os.read(sys.stdin.fileno(), min(65536, limit - len(incoming)))
        if not chunk:
            break
        incoming.extend(chunk)
    request, separator, _remainder = incoming.partition(b"\n")
    runtime = Path(os.environ["SIDE_PI_RUNTIME"])
    calls = runtime / "calls"
    calls.mkdir(exist_ok=True)
    (calls / f"{uuid.uuid4()}.json").write_bytes(request + separator)
    child = subprocess.Popen(["node", str(ROOT / "image/tool-connect.mjs")], stdin=subprocess.PIPE)

    def forward_stdin():
        try:
            while chunk := os.read(sys.stdin.fileno(), 65536):
                child.stdin.write(chunk)
                child.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                child.stdin.close()
            except BrokenPipeError:
                pass

    try:
        # Keep EOF/cancellation forwarding separate from waiting for the connector:
        # Pi leaves stdin open until a result arrives, including on socket failure.
        # Raw reads avoid buffered-stdin locks during daemon-thread shutdown.
        child.stdin.write(incoming)
        child.stdin.flush()
        threading.Thread(target=forward_stdin, daemon=True).start()
        raise SystemExit(child.wait())
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
