#!/usr/bin/env python3
"""Disposable native process boundary for the host owner regression tests."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_pi_owner
from host_pi_owner import HostPiOwner, detached_frontend, receive, run_interactive, send


def child():
    session = Path(sys.argv[sys.argv.index("--session") + 1])
    if session.read_text() == "fail-readiness":
        return 2
    if os.environ.get("FIXTURE_TERM_EXIT_ZERO"):
        def exit_zero_after_owner_cleanup(_signum, _frame):
            # Force the historical race: report normal native exit only after
            # worker-loss cleanup has already removed this pane's request file.
            while Path(os.environ["CODEX_SANDBOX_CD_REQUEST"]).exists():
                time.sleep(.005)
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, exit_zero_after_owner_cleanup)
    connection = socket.socket(socket.AF_UNIX)
    connection.connect(os.environ["CODEX_SANDBOX_PI_OWNER"])
    send(connection, {"op": "ready", "attachment": os.environ["CODEX_SANDBOX_PI_ATTACHMENT"], "session": str(session)})
    answer = receive(connection.makefile("rb"))
    if not answer.get("ok"):
        return 2
    connection.close()
    session.with_suffix(".ready").write_text(json.dumps({"owner": os.environ["CODEX_SANDBOX_PI_OWNER"],
                                                        "attachment": os.environ["CODEX_SANDBOX_PI_ATTACHMENT"],
                                                        "pid": os.getpid(), "argv": sys.argv[2:],
                                                        "sentinel": os.environ.get("HOST_OWNER_SECRET"),
                                                        "prompt": os.environ.get("CODEX_SANDBOX_PI_SPLIT_PROMPT"),
                                                        "pane": os.environ.get("TMUX_PANE"),
                                                        "cwd": os.getcwd()}))
    while not session.with_suffix(".exit").exists():
        handoff = session.with_suffix(".handoff")
        if handoff.exists():
            Path(os.environ["CODEX_SANDBOX_CD_REQUEST"]).write_text(handoff.read_text())
            return 0
        time.sleep(.05)
    return 0


def startup_main(arguments, bootstrap):
    report, failure = arguments
    probe = "import json, os, pathlib, sys; pathlib.Path(sys.argv[1]).write_text(json.dumps([os.isatty(fd) for fd in (0, 1, 2)]))"
    probe_path = report + ".child"
    # The guest worker is spawned before bootstrap, but must never inherit
    # the original UI terminal even while build startup still uses it.
    worker_path = report + ".worker"
    worker = subprocess.Popen([sys.executable, "-c", probe + "; import time; time.sleep(120)", worker_path],
                              stdin=subprocess.DEVNULL, stdout=host_pi_owner.OWNER_LOG_FD,
                              stderr=host_pi_owner.OWNER_LOG_FD)
    owner = None
    try:
        deadline = time.monotonic() + 3
        while not Path(worker_path).exists():
            if time.monotonic() > deadline:
                raise RuntimeError("worker did not report stdio")
            time.sleep(.005)
        startup_worker = json.loads(Path(worker_path).read_text())
        # Like Lima.build, inherit terminal stdin/stderr without capturing output.
        before = [os.isatty(fd) for fd in (0, 1, 2)]
        subprocess.run([sys.executable, "-c", "import os; os.write(2, b'build\\rready\\n')"], check=True)
        subprocess.run([sys.executable, "-c", probe, probe_path], check=True)
        build = json.loads(Path(probe_path).read_text())
        evidence = {"before": before, "build": build, "startup_worker": startup_worker}
        Path(report).write_text(json.dumps(evidence))
        if failure == "fail":
            os.write(2, b"error: startup failed\n")
            return 7
        owner = HostPiOwner(__file__, [], os.getcwd(), os.environ)
        owner.mark_bootstrapped()
        evidence["after"] = [os.isatty(fd) for fd in (0, 1, 2)]
        subprocess.run([sys.executable, "-c", probe, probe_path], check=True)
        evidence["worker"] = json.loads(Path(probe_path).read_text())
        Path(report).write_text(json.dumps(evidence))
        os.write(2, b"post-bootstrap diagnostic\n")
        return 0
    finally:
        worker.terminate()
        worker.wait()
        if owner is not None:
            owner.finish(True)


def owner_main(arguments, bootstrap):
    session, marker, worker_pid = arguments
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                              stdin=subprocess.DEVNULL, stdout=host_pi_owner.OWNER_LOG_FD,
                              stderr=host_pi_owner.OWNER_LOG_FD)
    Path(worker_pid).write_text(str(worker.pid))
    wrapper = __file__ if not os.environ.get("FIXTURE_BAD_WRAPPER") else str(Path(marker).with_name("missing-wrapper"))
    owner = HostPiOwner(wrapper, ["--session-dir", str(Path(session).parent / "obsolete-directory"),
                                 "--session", session, "ORIGINAL_PROMPT"], os.getcwd(), os.environ, timeout=3)
    owner.original.pane = os.environ.get("TMUX_PANE")
    owner.mark_bootstrapped()
    owner.start()
    send(bootstrap, owner.launch_spec(owner.original))
    result = 0
    try:
        owner.wait(worker)
    except RuntimeError:
        result = 1
    finally:
        worker.terminate()
        worker.wait()
        Path(marker).write_text("cleaned")
        owner.finish(True)
    return result


if __name__ == "__main__":
    if sys.argv[1:2] == ["startup"]:
        raise SystemExit(detached_frontend(sys.argv[2:], startup_main))
    if sys.argv[1:2] == ["launcher"]:
        raise SystemExit(detached_frontend(sys.argv[2:], owner_main))
    if sys.argv[1:2] == ["child"]:
        raise SystemExit(child())
    if sys.argv[1:2] != ["--sandbox-interactive"]:
        raise SystemExit("fixture requires private interactive marker")
    raise SystemExit(run_interactive([sys.executable, __file__, "child", *sys.argv[2:]]))
