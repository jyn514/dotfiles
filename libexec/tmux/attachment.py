"""Client source capture and source-aware tmux attachment (POSIX hosts)."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import syslog
import time


DISABLE_OPTION = "@attach-session-disable"


def native_tmux() -> str:
    wrapper = Path(__file__).resolve().parents[2] / "bin/tmux"
    paths = [entry for entry in os.get_exec_path()
             if (Path(entry or ".") / "tmux").resolve() != wrapper.resolve()]
    executable = shutil.which("tmux", path=os.pathsep.join(paths))
    if executable is None:
        raise RuntimeError("real tmux not found on PATH")
    return executable


def source(environment: dict[str, str]) -> str | None:
    connection = environment.get("SSH_CONNECTION", "")
    if not connection:
        return None if environment.get("SSH_TTY") or environment.get("SSH_CLIENT") else "local"
    fields = connection.split()
    if len(fields) != 4:
        return None
    try:
        address = ipaddress.ip_address(fields[0])
        ipaddress.ip_address(fields[2])
        if not all(0 < int(fields[index]) <= 65535 for index in (1, 3)):
            return None
    except ValueError:
        return None
    return str(address)


def registry() -> Path:
    # A fixed host-local path works when SSH and desktop clients have different
    # TMPDIR/XDG_RUNTIME_DIR values. These files never leave this host.
    path = Path("/tmp") / f"dotfiles-tmux-sources-{os.getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"unsafe source directory: {path}")
    return path


def open_private(path: Path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise RuntimeError(f"unsafe attachment file: {path}")
    return os.fdopen(fd, "r+")


def launch(executable: str, arguments: list[str]) -> int:
    """Preserve argv, environment, stdio and process group; own source lifetime."""
    directory = registry()
    identity = source(dict(os.environ))
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(write_fd)
        ready = os.read(read_fd, 1)
        os.close(read_fd)
        if ready != b"1":
            os._exit(1)
        try:
            os.execv(executable, [executable, *arguments])
        except OSError as error:
            print(f"tmux launcher: {error}", file=sys.stderr)
            os._exit(127)

    os.close(read_fd)
    path = directory / str(pid)
    record = None
    handlers = {}
    def forward(signum, _frame):
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass
    try:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP):
            handlers[signum] = signal.signal(signum, forward)
        record = open_private(path)
        fcntl.flock(record, fcntl.LOCK_EX)
        record.seek(0)
        record.truncate()
        json.dump(identity, record)
        record.flush()
        os.write(write_fd, b"1")
        os.close(write_fd)
        write_fd = -1
        while True:
            _, status = os.waitpid(pid, os.WUNTRACED)
            if not os.WIFSTOPPED(status):
                break
            # suspend-client stops tmux alone, rather than the entire foreground
            # group. Let the shell observe a stopped launcher and reclaim its tty.
            os.kill(os.getpid(), signal.SIGSTOP)
            os.kill(pid, signal.SIGCONT)
        return os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 128 + os.WTERMSIG(status)
    finally:
        if write_fd != -1:
            os.close(write_fd)
            os.waitpid(pid, 0)
        if record is not None:
            path.unlink(missing_ok=True)
            record.close()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def client_source(pid: str) -> str | None:
    if not pid.isdigit():
        return None
    try:
        with (registry() / pid).open() as record:
            try:
                fcntl.flock(record, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                value = json.load(record)
                if value == "local":
                    return value
                if isinstance(value, str):
                    return str(ipaddress.ip_address(value))
            # An unlocked record has no live launcher owner (including after
            # SIGKILL). Never infer local identity from a stale PID file.
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def source_label(identity: str | None) -> str:
    if identity is None:
        return "unknown"
    if identity == "local":
        return identity
    try:
        result = subprocess.run(["tailscale", "whois", "--json", identity],
                                capture_output=True, timeout=1, check=False)
        if result.returncode == 0:
            name = json.loads(result.stdout).get("Node", {}).get("Name")
            if isinstance(name, str) and name:
                return name.rstrip(".")
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        pass
    return identity


@contextmanager
def selection_lock(socket: str, server_pid: str):
    # Empty lock files are coordination handles, not persisted source state.
    # flock releases on process death; never unlink a lock other waiters use.
    path = Path(socket).parent / f".attachment-{server_pid}.lock"
    with open_private(path) as lock:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("attachment selection timed out; keeping new session")
                time.sleep(.02)
        yield


class Tmux:
    def __init__(self, executable: str, socket: str):
        self.command = [executable, "-S", socket]

    def run(self, *arguments: str) -> str:
        result = subprocess.run([*self.command, *arguments], capture_output=True, text=True,
                                timeout=5, check=False)
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, result.args, stderr=result.stderr)
        return result.stdout.rstrip("\n")

    def clients(self) -> list[tuple[str, str, str]]:
        return [tuple(line.split("\t")) for line in self.run(
            "list-clients", "-F", "#{client_name}\t#{client_pid}\t#{session_id}").splitlines()]

    def candidates(self, created: str, identity: str | None) -> list[str]:
        clients = self.clients()
        detached, attached = [], []
        for session in self.run("list-sessions", "-F", "#{session_id}").splitlines():
            if session == created:
                continue
            occupants = [client_source(pid) for _, pid, current in clients if current == session]
            if not occupants:
                detached.append(session)
            elif identity is not None and all(item is not None and item != identity for item in occupants):
                attached.append(session)
        return detached + attached


def attach(tmux: Tmux, socket: str, client: str, created: str, server_pid: str) -> tuple[str | None, str] | None:
    if tmux.run("show-option", "-sqv", DISABLE_OPTION):
        return
    # The hook supplies stable targets before numeric session renaming.
    if not client or tmux.run("display-message", "-p", "-c", client, "#{client_last_session}"):
        return
    with selection_lock(socket, server_pid):
        live = tmux.clients()
        incoming = next((item for item in live if item[0] == client and item[2] == created), None)
        if incoming is None:
            return
        identity = client_source(incoming[1])
        for _ in range(3):
            candidates = tmux.candidates(created, identity)
            if not candidates:
                return
            target = candidates[0]
            # Re-read native membership immediately before the mutation.
            if target not in tmux.candidates(created, identity):
                continue
            try:
                tmux.run("switch-client", "-c", client, "-t", target)
            except subprocess.CalledProcessError:
                if target not in tmux.run("list-sessions", "-F", "#{session_id}").splitlines():
                    continue
                raise
            # No destroy-unattached option is changed: failed switches cannot
            # arm a retained session for destruction on a later detach.
            if not any(current == created for _, _, current in tmux.clients()):
                tmux.run("kill-session", "-t", created)
            break
        else:
            return
    return identity, target


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tmux", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--client", default="")
    parser.add_argument("--session", default="")
    parser.add_argument("--server-pid", default="")
    parser.add_argument("--log", action="store_true")
    parser.add_argument("mode", nargs="?", choices=("disable", "enable"))
    options = parser.parse_args(arguments)
    tmux = Tmux(options.tmux, options.socket)
    def report(message: str, error: bool = False) -> None:
        if options.log:
            syslog.openlog("tmux-session")
            syslog.syslog(syslog.LOG_ERR if error else syslog.LOG_INFO, message)
        else:
            print(message, file=sys.stderr if error else sys.stdout)
    try:
        if options.mode == "disable":
            tmux.run("set-option", "-s", DISABLE_OPTION, "1")
        elif options.mode == "enable":
            tmux.run("set-option", "-su", DISABLE_OPTION)
        else:
            selected = attach(tmux, options.socket, options.client, options.session, options.server_pid)
            if selected is not None:
                identity, target = selected
                # Name lookup cannot hold up another client's selection.
                report(f"attached {source_label(identity)} to session {target}")
        return 0
    except subprocess.CalledProcessError as error:
        report(f"tmux attachment: {error.stderr.strip()}", error=True)
        return error.returncode
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report(f"tmux attachment: {error}", error=True)
        return 1
