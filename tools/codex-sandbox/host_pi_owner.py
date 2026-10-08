"""Bounded, process-local interactive leases for one accepted sandbox workload.

No tool connection is a lease. Tokens name one reserved/live wrapper; short-lived
extension requests are authenticated by an already live wrapper connection.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import subprocess
import tempfile
import threading
import time

# Assigned only in the forked standalone owner; never serialized into tmux argv.
OWNER_LOG_PATH = None
OWNER_LOG_FD = None


def _redirect_owner_stdio():
    """Drop the startup terminal before any interactive lease can be delivered."""
    import sys
    if OWNER_LOG_FD is None:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os.dup2(OWNER_LOG_FD, 1)
    os.dup2(OWNER_LOG_FD, 2)
    null = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(null, 0)
    finally:
        os.close(null)


def send(connection, value):
    connection.sendall((json.dumps(value) + "\n").encode())


def receive(stream):
    line = stream.readline(1024 * 1024 + 1)
    if not line or len(line) > 1024 * 1024:
        raise ValueError("connection closed or request too large")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("request must be an object")
    return value


@dataclass
class Attachment:
    token: str
    cd_request: str
    deadline: float
    connection: socket.socket | None = None
    session: Path | None = None
    session_directory: Path | None = None
    pane: str | None = None
    ready: bool = False
    prompt: str | None = None


class HostPiOwner:
    """Own sockets until cleanup ACK; callers own existing workload cleanup."""
    def __init__(self, wrapper, arguments, cwd, environment, *, timeout=30.0):
        self.directory = tempfile.TemporaryDirectory(prefix="sandbox-pi-owner-")
        self.path = str(Path(self.directory.name) / "owner.sock")
        self.wrapper = str(wrapper)
        self.arguments = list(arguments)
        self.cwd = str(cwd)
        self.environment = dict(environment)
        self.timeout = timeout
        self.lock = threading.Condition()
        self.attachments = {}
        self.final_connections = []
        self.stopping = False
        self.failure = None
        self.pane_changed = None
        self.log_offset = 0
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen()
        self.server.settimeout(.1)
        # The bootstrap reservation precedes both service threads and tmux launch.
        self.original = self.reserve()

    def reserve(self):
        with self.lock:
            if self.stopping:
                raise ValueError("workload is stopping")
            token = secrets.token_urlsafe(32)
            request = Path(self.directory.name) / (token + ".cd")
            request.touch(mode=0o600)
            item = Attachment(token, str(request), time.monotonic() + self.timeout)
            self.attachments[token] = item
            return item

    def launch_spec(self, item, arguments=None):
        environment = dict(self.environment)
        environment.update(CODEX_SANDBOX_PI_OWNER=self.path,
                           CODEX_SANDBOX_PI_ATTACHMENT=item.token,
                           CODEX_SANDBOX_CD_REQUEST=item.cd_request)
        environment.pop("CODEX_SANDBOX_PI_SPLIT_PROMPT", None)
        if item.prompt:
            environment["CODEX_SANDBOX_PI_SPLIT_PROMPT"] = item.prompt
        return {"argv": [self.wrapper, "--sandbox-interactive", *(self.arguments if arguments is None else arguments)],
                "cwd": self.cwd, "env": environment}

    def mark_bootstrapped(self):
        # Guest provisioning is not Pi UI startup. Arm the original reservation
        # only when its launch spec can actually be delivered to the frontend.
        # Side reservations still start before their tmux effect.
        with self.lock:
            self.original.deadline = time.monotonic() + self.timeout
        _redirect_owner_stdio()
        if OWNER_LOG_PATH is not None:
            import sys
            sys.stdout.flush()
            sys.stderr.flush()
            self.log_offset = os.stat(OWNER_LOG_PATH).st_size

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while not self.stopping:
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                self.expire()
                continue
            except OSError:
                return
            threading.Thread(target=self.handle, args=(connection,), daemon=True).start()

    def expire(self):
        with self.lock:
            for item in list(self.attachments.values()):
                if not item.ready and time.monotonic() > item.deadline:
                    if item.connection is not None:
                        try:
                            send(item.connection, {"ok": False, "event": "worker-loss",
                                                   "error": "host Pi startup timed out"})
                        except OSError:
                            pass
                    self.drop(item)

    def drop(self, item, connection=None):
        with self.lock:
            self.attachments.pop(item.token, None)
            if self.pane_changed is not None:
                pane = next((peer.pane for peer in self.attachments.values()
                             if peer.pane is not None and peer.connection is not None and peer.ready), None)
                self.pane_changed(pane)
            self.lock.notify_all()
            if not self.attachments:
                self.stopping = True
                if connection is not None:
                    self.final_connections.append(connection)
                self.lock.notify_all()
                return True
            return False

    def handle(self, connection):
        keep = False
        item = None
        connection.settimeout(5)
        stream = connection.makefile("rb")
        try:
            request = receive(stream)
            operation = request.get("op")
            with self.lock:
                item = self.attachments.get(request.get("attachment"))
                if item is None or self.stopping:
                    raise ValueError("unknown or expired attachment")
                if operation == "attach":
                    if item.connection is not None:
                        raise ValueError("attachment already connected")
                    item.connection = connection
                elif item.connection is None:
                    raise ValueError("attachment is not connected")
            connection.settimeout(None)
            if operation == "attach":
                connection.settimeout(None)
                spec = self.launch_spec(item)
                send(connection, {"ok": True, "env": spec["env"], "cwd": spec["cwd"]})
                request = receive(stream)
                if request.get("op") != "release":
                    raise ValueError("lifetime connection expects release")
                with self.lock:
                    final = self.drop(item, connection)
                    keep = final
                    if not final:
                        send(connection, {"ok": True, "final": False})
            elif operation == "ready":
                value = request.get("session")
                if value is None:
                    proposed = Path(request.get("sessionDir", ""))
                    if not proposed.is_absolute():
                        raise ValueError("sessionDir must be an absolute path")
                    parent = proposed.resolve(strict=True)
                    session = None
                else:
                    if not isinstance(value, str) or not value:
                        raise ValueError("session must be a nonempty path")
                    proposed = Path(value)
                    if not proposed.is_absolute():
                        raise ValueError("session must be an absolute path")
                    # Pi lazily publishes new session files after its first assistant.
                    parent = proposed.parent.resolve(strict=True)
                    session = parent / proposed.name
                    if session.exists() and (session.is_symlink() or not session.is_file()):
                        raise ValueError("session must be a regular file")
                if not parent.is_dir():
                    raise ValueError("session directory must exist")
                with self.lock:
                    if item.token not in self.attachments or self.stopping:
                        raise ValueError("attachment disconnected")
                    # Native human session switches reannounce SDK-selected
                    # directories; requests remain tied to this live attachment.
                    item.session = session
                    item.session_directory = parent
                    item.ready = True
                    if self.pane_changed is not None and self.original.token not in self.attachments:
                        self.pane_changed(item.pane)
                    self.lock.notify_all()
                send(connection, {"ok": True})
            elif operation == "side":
                pane = self.side(item, request.get("session"), request.get("prompt"))
                send(connection, {"ok": True, "pane": pane})
            else:
                raise ValueError("unknown operation")
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            try:
                send(connection, {"ok": False, "error": str(error)})
            except OSError:
                pass
        finally:
            stream.close()
            if item is not None and item.connection is connection:
                self.drop(item)
            if not keep:
                connection.close()

    def side(self, source, snapshot, prompt=None):
        if prompt is not None and not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        if not self.environment.get("TMUX") or not self.environment.get("TMUX_PANE"):
            raise ValueError("/split requires tmux")
        path = Path(snapshot).resolve(strict=True)
        with self.lock:
            if source.token not in self.attachments or source.connection is None:
                raise ValueError("attachment disconnected")
            if source.session_directory is None or path.parent != source.session_directory or not path.is_file():
                raise ValueError("snapshot must belong to the invoking Pi session directory")
            item = self.reserve()
            item.prompt = prompt
        pane = None
        try:
            # Never replay the source's prompts, output modes, or original
            # CLI model overrides. The snapshot carries model/thinking metadata.
            spec = self.launch_spec(item, ["--session-dir", str(path.parent), "--session", str(path)])
            # Captured host secrets travel only over the private attach socket,
            # never tmux command argv (including its failure diagnostics).
            launch_environment = {"CODEX_SANDBOX_PI_OWNER": self.path,
                                  "CODEX_SANDBOX_PI_ATTACHMENT": item.token}
            if "HOME" in self.environment:
                launch_environment["HOME"] = self.environment["HOME"]
            command = shlex.join(["env", *(f"{k}={v}" for k, v in launch_environment.items()), *spec["argv"]])
            result = subprocess.run(["tmux", "split-window", "-P", "-F", "#{pane_id}",
                                     "-t", source.pane or self.environment["TMUX_PANE"], "-c", self.cwd, command],
                                    env=self.environment, text=True, capture_output=True, check=True,
                                    timeout=self.timeout)
            pane = result.stdout.strip()
            if not pane.startswith("%") or not pane[1:].isdigit():
                raise ValueError("tmux returned an invalid pane ID")
            with self.lock:
                item.pane = pane
                if self.pane_changed is not None and source.token not in self.attachments and item.ready:
                    self.pane_changed(pane)
            deadline = time.monotonic() + self.timeout
            with self.lock:
                while not item.ready and item.token in self.attachments and not self.stopping:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self.lock.wait(min(.1, remaining))
                if not item.ready or item.token not in self.attachments:
                    raise ValueError("side Pi did not become ready")
            return pane
        except BaseException:
            self.drop(item)
            if pane is not None:
                subprocess.run(["tmux", "kill-pane", "-t", pane], env=self.environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if item.connection is not None:
                try:
                    send(item.connection, {"ok": False, "event": "worker-loss", "error": "side startup failed"})
                except OSError:
                    pass
            raise

    def wait(self, worker):
        while True:
            if worker.poll() is not None:
                self.worker_lost()
                raise RuntimeError("guest tool worker stopped while host Pi was running")
            with self.lock:
                if self.stopping:
                    return
                self.lock.wait(.1)
            self.expire()

    def worker_lost(self):
        with self.lock:
            self.failure = "guest tool worker stopped"
            self.stopping = True
            for item in self.attachments.values():
                if item.connection is not None:
                    try:
                        send(item.connection, {"ok": False, "event": "worker-loss", "error": self.failure})
                    except OSError:
                        pass
            self.lock.notify_all()

    def finish(self, succeeded):
        """Only call after workload contexts, relays and session locks are cleaned."""
        with self.lock:
            self.stopping = True
            for connection in self.final_connections:
                try:
                    logs = ""
                    if OWNER_LOG_PATH is not None:
                        import sys
                        sys.stdout.flush()
                        sys.stderr.flush()
                        with open(OWNER_LOG_PATH, "r") as log:
                            log.seek(self.log_offset)
                            logs = log.read()[-65536:]
                    okay = bool(succeeded) and self.failure is None
                    send(connection, {"ok": okay, "final": True,
                                      **({"logs": logs} if logs else {}),
                                      **({} if okay else {"error": self.failure or "sandbox cleanup failed"})})
                except OSError:
                    pass
                connection.close()
        self.server.close()
        for item in list(self.attachments.values()):
            if item.connection is not None:
                try:
                    item.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                item.connection.close()
        self.directory.cleanup()


def run_interactive(command: list[str]) -> int:
    """Wrapper-only entry: one held lease per Pi child, never per subagent."""
    import signal
    connection = socket.socket(socket.AF_UNIX)
    connection.connect(os.environ["CODEX_SANDBOX_PI_OWNER"])
    stream = connection.makefile("rb")
    send(connection, {"op": "attach", "attachment": os.environ["CODEX_SANDBOX_PI_ATTACHMENT"]})
    answer = receive(stream)
    if not answer.get("ok"):
        raise RuntimeError(answer.get("error", "attachment rejected"))
    fresh_pane = os.environ.get("TMUX_PANE")
    os.environ.clear()
    os.environ.update(answer["env"])
    if fresh_pane is not None:
        os.environ["TMUX_PANE"] = fresh_pane
    os.chdir(answer["cwd"])
    child = subprocess.Popen(command, preexec_fn=_parent_death_signal())
    lost = threading.Event()
    released = threading.Event()
    response = {}

    def monitor():
        try:
            answer = receive(stream)
            response.update(answer)
            if answer.get("event") == "worker-loss":
                lost.set()
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
            released.set()
        except (OSError, ValueError):
            lost.set()
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
            released.set()

    threading.Thread(target=monitor, daemon=True).start()
    previous = {}
    def forward(signum, _frame):
        if child.poll() is None:
            child.send_signal(signum)
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, forward)
    try:
        result = child.wait()
        # Capture handoff before the final ACK removes private attachment files.
        handoff = None
        request_path = os.environ.get("CODEX_SANDBOX_CD_REQUEST")
        if result == 0 and request_path and not lost.is_set():
            try:
                text = Path(request_path).read_text()
            except FileNotFoundError:
                # A confirmed owner-loss response can race removal with this
                # read. Never hide that reason behind its deleted request file.
                if not lost.is_set():
                    raise
            else:
                if text:
                    handoff = json.loads(text)
        if not lost.is_set():
            send(connection, {"op": "release"})
            released.wait()
        logs = response.get("logs", "")
        if logs:
            import sys
            sys.stderr.write(logs)
        if lost.is_set() or not response.get("ok"):
            import sys
            if not any(line.startswith("error:") for line in logs.splitlines()):
                print("error: " + response.get("error", "sandbox owner connection lost"), file=sys.stderr)
            return 1
        if handoff is None:
            return result if result >= 0 else 128 - result
        if not isinstance(handoff, dict) or set(handoff) != {"destination", "session"}:
            raise ValueError("invalid directory handoff")
        destination = handoff["destination"]
        session = handoff["session"]
        if not isinstance(destination, str) or not destination or (session is not None and not isinstance(session, str)):
            raise ValueError("invalid directory handoff")
        launcher = os.environ["CODEX_SANDBOX_CD_VALIDATE"]
        checked = subprocess.run([launcher, "validate-cd", destination], text=True,
                                 capture_output=True, check=True)
        destination = json.loads(checked.stdout)["destination"]
        arguments = []
        if "--session-dir" in command:
            index = command.index("--session-dir")
            directory = Path(command[index + 1]).expanduser().resolve()
            arguments += ["--session-dir", str(directory)]
        if session is not None:
            session = str(Path(session).resolve(strict=True))
            arguments += ["--fork", session]
        import uuid
        arguments += ["--session-id", str(uuid.uuid4())]
        environment = dict(os.environ)
        for key in ("CODEX_SANDBOX_PI_OWNER", "CODEX_SANDBOX_PI_ATTACHMENT", "CODEX_SANDBOX_CD_REQUEST"):
            environment.pop(key, None)
        environment["CODEX_SANDBOX_PREVIOUS_CWD"] = os.getcwd()
        # Replace this invoking terminal client rather than accumulating a chain
        # of lease-free wrappers whose signals would target obsolete Pi children.
        os.chdir(destination)
        os.execve(launcher, [launcher, *arguments], environment)
        return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()
        stream.close()


def detached_frontend(arguments, owner_main):
    """Fork before startup resources/threads; UI retains its original terminal."""
    import sys
    bootstrap, owner_socket = socket.socketpair()
    log_fd, log_name = tempfile.mkstemp(prefix="sandbox-owner-startup-")
    startup_log = open(log_name, "r")
    interactive_startup = sys.stdin.isatty() and sys.stderr.isatty()
    pid = os.fork()
    if pid == 0:
        global OWNER_LOG_PATH, OWNER_LOG_FD
        OWNER_LOG_PATH = log_name
        OWNER_LOG_FD = log_fd
        startup_log.close()
        bootstrap.close()
        os.setsid()
        # Lima's build needs real stdin/stderr TTYs for SSH's guest PTY.
        # Retain only the original standard descriptors during provisioning;
        # mark_bootstrapped drops them before delivering the first UI lease.
        # Long-lived startup workers must explicitly use OWNER_LOG_FD/DEVNULL.
        if not interactive_startup:
            _redirect_owner_stdio()
        # Reconfigure buffered streams after fork so progress is promptly visible.
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
        status = 1
        try:
            status = owner_main(arguments, owner_socket)
            try:
                send(owner_socket, {"exit": status})
            except OSError:
                pass
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            owner_socket.close()
            os.close(log_fd)
            OWNER_LOG_FD = None
            try:
                os.unlink(log_name)
            except OSError:
                pass
        os._exit(status)
    owner_socket.close()
    os.close(log_fd)
    import select
    stream = bootstrap.makefile("rb")
    import signal
    previous = {}
    def interrupt_startup(signum, _frame):
        # Before bootstrap there can be no peers. Stop the sole startup owner
        # through its normal cleanup path and keep draining its diagnostics/ACK.
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, interrupt_startup)
    try:
        with startup_log as log:
            while True:
                progress = log.read()
                if progress:
                    sys.stderr.write(progress)
                    sys.stderr.flush()
                readable, _, _ = select.select([bootstrap], [], [], .1)
                if not readable:
                    continue
                try:
                    answer = receive(stream)
                except ValueError:
                    return 1
                progress = log.read()
                if progress:
                    sys.stderr.write(progress)
                if "argv" in answer:
                    # Exec retains pane PID/session and makes wrapper the terminal
                    # client. Owner PID is neither its child worker nor foreground.
                    try:
                        os.chdir(answer["cwd"])
                        os.execve(answer["argv"][0], answer["argv"], answer["env"])
                    except OSError as error:
                        # Consume and release the one-use reservation immediately
                        # rather than leaving a failed bootstrap until its deadline.
                        lease = socket.socket(socket.AF_UNIX)
                        try:
                            lease.connect(answer["env"]["CODEX_SANDBOX_PI_OWNER"])
                            lease_stream = lease.makefile("rb")
                            send(lease, {"op": "attach", "attachment": answer["env"]["CODEX_SANDBOX_PI_ATTACHMENT"]})
                            if receive(lease_stream).get("ok"):
                                send(lease, {"op": "release"})
                                receive(lease_stream)
                            lease_stream.close()
                        except (OSError, ValueError):
                            pass
                        finally:
                            lease.close()
                        print(f"error: could not start host Pi: {error}", file=sys.stderr)
                        return 1
                return int(answer.get("exit", 1))
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        stream.close()
        bootstrap.close()


def _parent_death_signal():
    """Linux safeguard for a wrapper killed without its terminal's normal HUP.

    Hosts without prctl retain terminal/process-group HUP semantics. The detached
    workload owner never uses this hook: it must outlive its original UI client.
    """
    import sys
    if sys.platform != "linux":
        return None
    import ctypes
    import signal
    libc = ctypes.CDLL(None, use_errno=True)
    parent = os.getpid()
    def arm():
        for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, signal.SIG_DFL)
        # A parent can itself have inherited SIGTERM=ignored. SIGKILL guarantees
        # the terminal client cannot survive a wrapper killed without normal HUP.
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            os._exit(126)
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGKILL)
    return arm
