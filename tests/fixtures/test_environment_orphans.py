"""Native orphan-process fixture, with an outer guardian even for broken wrappers."""
import ctypes
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time


def subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot contain orphan fixture")


def exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup():
    # The guardian owns this whole process subtree. Never let a failing test
    # donate its daemon to a container's non-reaping PID 1.
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    while pids := children.read_text().split():
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        os.waitpid(-1, 0)


def command(mode, state):
    reader, writer = os.pipe()
    launcher = os.fork()
    if launcher == 0:
        os.close(reader)
        os.setsid()
        if os.fork():
            os._exit(0)
        # Daemonized work must not hold the guardian's captured output open.
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
        if mode == "resistant":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        state.write_text(json.dumps({"pid": os.getpid(), "home": os.environ["HOME"]}))
        os.write(writer, b"1")
        os.close(writer)
        if mode in ("exited", "nested"):
            os._exit(0)
        while True:
            signal.pause()
    os.close(writer)
    os.waitpid(launcher, 0)
    assert os.read(reader, 1) == b"1"
    os.close(reader)
    if mode in ("exited", "nested"):
        orphan = json.loads(state.read_text())["pid"]
        deadline = time.monotonic() + 2
        while exists(orphan) and time.monotonic() < deadline:
            time.sleep(.01)
        print(json.dumps({"reaped_while_running": not exists(orphan)}), flush=True)
    if mode == "signal":
        os.kill(os.getpid(), signal.SIGTERM)
    if mode == "forwarded":
        print("ready", flush=True)
        while True:
            signal.pause()
    return 23


def guard(wrapper, mode):
    subreaper()
    with tempfile.TemporaryDirectory(prefix="test-orphan-guardian-") as directory:
        state = Path(directory) / "orphan.json"
        arguments = [wrapper, sys.executable, __file__, "command", mode, str(state)]
        if mode == "nested":
            arguments.insert(1, wrapper)
        sibling = subprocess.Popen([sys.executable, __file__, "idle"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process = None
        try:
            process = subprocess.Popen(arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if mode == "forwarded":
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    assert selector.select(timeout=5), "command did not become ready"
                assert process.stdout.readline() == "ready\n"
                process.send_signal(signal.SIGTERM)
            output, errors = process.communicate(timeout=10)
            orphan = json.loads(state.read_text())
            report = {"status": process.returncode, "errors": errors,
                      "remaining": exists(orphan["pid"]),
                      "home_removed": not Path(orphan["home"]).exists(),
                      "unrelated_alive": sibling.poll() is None}
            if mode in ("exited", "nested"):
                report.update(json.loads(output))
            print(json.dumps(report), flush=True)
        finally:
            try:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
            finally:
                if sibling.poll() is None:
                    sibling.kill()
                sibling.wait(timeout=5)
                cleanup()


if __name__ == "__main__":
    if sys.argv[1] == "idle":
        signal.pause()
    elif sys.argv[1] == "guard":
        guard(sys.argv[2], sys.argv[3])
    else:
        sys.exit(command(sys.argv[2], Path(sys.argv[3])))
