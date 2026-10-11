"""Source-aware attachment through the real tmux launcher and production hook."""

import importlib.util
import json
import os
import pty
import select
import shlex
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("attachment", ROOT / "libexec/tmux/attachment.py")
attachment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attachment)
NATIVE = shutil.which("tmux", path=os.pathsep.join(
    entry for entry in os.get_exec_path() if Path(entry).resolve() != ROOT / "bin"))


class SourceTests(unittest.TestCase):
    def test_sources_ignore_ports_and_normalize_ipv6(self):
        cases = [
            ({}, "local"),
            ({"SSH_TTY": "/dev/pts/0"}, None),
            ({"SSH_CLIENT": "100.64.0.1 12 22"}, None),
            ({"SSH_CONNECTION": "100.64.0.1 123 100.64.0.2 22"}, "100.64.0.1"),
            ({"SSH_CONNECTION": "100.64.0.1 456 100.64.0.2 22"}, "100.64.0.1"),
            ({"SSH_CONNECTION": "fd7a:115c:a1e0:0:0:0:0:1 123 fd7a:115c:a1e0::2 22"},
             "fd7a:115c:a1e0::1"),
            ({"SSH_CONNECTION": "invalid"}, None),
            ({"SSH_CONNECTION": "100.64.0.1 0 100.64.0.2 22"}, None),
            ({"SSH_CONNECTION": "100.64.0.1 123 invalid 22"}, None),
        ]
        for environment, expected in cases:
            with self.subTest(environment=environment):
                self.assertEqual(attachment.source(environment), expected)

    def test_tailscale_labels_do_not_define_identity(self):
        result = subprocess.CompletedProcess([], 0, b'{"Node":{"Name":"laptop.tail.ts.net."}}')
        with mock.patch.object(attachment.subprocess, "run", return_value=result):
            self.assertEqual(attachment.source_label("100.64.0.1"), "laptop.tail.ts.net")
        for result in (
            subprocess.CompletedProcess([], 1, b""),
            subprocess.CompletedProcess([], 0, b"invalid"),
            subprocess.CompletedProcess([], 0, b"{}"),
            subprocess.CompletedProcess([], 0, b'{"Node":null}'),
        ):
            with mock.patch.object(attachment.subprocess, "run", return_value=result):
                self.assertEqual(attachment.source_label("100.64.0.1"), "100.64.0.1")
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("tailscale", 1)):
            with mock.patch.object(attachment.subprocess, "run", side_effect=error):
                self.assertEqual(attachment.source_label("100.64.0.1"), "100.64.0.1")

    def test_unlocked_record_is_unknown_even_if_pid_is_live(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, str(os.getpid())).write_text('"local"')
            with mock.patch.object(attachment, "registry", return_value=Path(directory)):
                self.assertIsNone(attachment.client_source(str(os.getpid())))

    def test_query_failure_preserves_return_status_and_diagnostic(self):
        error = subprocess.CalledProcessError(23, ["tmux"], stderr="query failed\n")
        with mock.patch.object(attachment.Tmux, "run", side_effect=error), \
             mock.patch("sys.stderr") as diagnostic:
            self.assertEqual(attachment.main(["--tmux", "tmux", "--socket", "/unused"]), 23)
            self.assertIn("query failed", str(diagnostic.write.call_args_list))


@unittest.skipUnless(NATIVE, "tmux is required")
class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.socket = str(self.directory / "socket")
        self.environment = dict(os.environ, TERM="xterm-256color")
        for name in ("TMUX", "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT"):
            self.environment.pop(name, None)
        self.clients = []
        self.addCleanup(self.cleanup_clients)
        self.addCleanup(self.stop_server)
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "seed", "sleep", "300")
        self.tmux("set-option", "-g", "update-environment", "SSH_CONNECTION")
        # Use the real configured hook, and a private installed entrypoint.
        config = self.directory / ".config/tmux"
        config.mkdir(parents=True)
        (config / "attach-session.sh").symlink_to(ROOT / "libexec/tmux/attach-session.sh")
        self.tmux("set-environment", "-g", "HOME", str(self.directory))
        hook = next(line for line in (ROOT / "config/tmux/tmux.conf").read_text().splitlines()
                    if line.startswith("set-hook -g after-new-session[1]"))
        hook = hook.replace(" --log ", " ")
        file = self.directory / "hook.conf"
        file.write_text(hook + "\n")
        self.tmux("source-file", str(file))
        self.assertIn("--socket=", self.tmux("show-hooks", "-g", "after-new-session"))

    def tmux(self, *arguments, check=True):
        result = subprocess.run([NATIVE, "-S", self.socket, *arguments],
                                env=self.environment, capture_output=True, text=True, timeout=10)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def stop_server(self):
        self.tmux("kill-server", check=False)

    def cleanup_clients(self):
        for process in self.clients:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.02)
        self.fail("tmux operation did not complete")

    def client_rows(self):
        return [line.split("\t") for line in self.tmux(
            "list-clients", "-F", "#{client_pid}\t#{session_name}").splitlines()]

    def start(self, ip=None, command="new-session", name="new", wrapped=True, wait=True):
        environment = self.environment.copy()
        if ip is not None:
            environment["SSH_CONNECTION"] = f"{ip} 12345 100.64.0.9 22"
        before = {row[0] for row in self.client_rows()}
        process = subprocess.Popen(
            [str(ROOT / "bin/tmux") if wrapped else NATIVE, "-S", self.socket,
             "-C", command, "-t" if command == "attach-session" else "-s", name],
            env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.clients.append(process)
        if not wait:
            return process
        self.wait_for(lambda: any(row[0] not in before for row in self.client_rows()))
        pid = next(row[0] for row in self.client_rows() if row[0] not in before)
        # Round-trip through the client's own command queue waits for its hook.
        process.stdin.write(b"display-message -p finished\n")
        process.stdin.flush()
        self.wait_for(lambda: process.poll() is not None or self.ready(process))
        self.assertIsNone(process.poll())
        self.assertNotIn(b"tmux attachment:", getattr(process, "received", b""))
        return process, pid

    def ready(self, process):
        # Control output is unbuffered and read with select, avoiding readline's
        # interaction with buffered notifications.
        import select
        if select.select([process.stdout], [], [], 0)[0]:
            data = os.read(process.stdout.fileno(), 65536)
            previous = getattr(process, "received", b"")
            process.received = previous + data
        return b"finished" in getattr(process, "received", b"")

    def session(self, pid):
        return next(row[1] for row in self.client_rows() if row[0] == pid)

    def test_local_clients_do_not_share_but_remote_sources_do(self):
        _, local = self.start(name="first")
        self.assertEqual(self.session(local), "seed")
        _, other_local = self.start(name="local2")
        self.assertEqual(self.session(other_local), "local2")
        _, remote = self.start("100.64.0.1", name="remote")
        self.assertEqual(self.session(remote), "local2")
        _, other_remote = self.start("100.64.0.2", name="remote2")
        self.assertEqual(self.session(other_remote), "local2")
        _, same_remote = self.start("100.64.0.1", name="remote3")
        self.assertEqual(self.session(same_remote), "seed")
        _, third_remote = self.start("100.64.0.1", name="remote4")
        self.assertEqual(self.session(third_remote), "remote4")

    def test_existing_sources_survive_session_environment_overwrite(self):
        _, local = self.start(name="first")
        _, remote = self.start("100.64.0.1", command="attach-session", name="seed")
        self.assertIn("100.64.0.1", self.tmux("show-environment", "-t", "seed", "SSH_CONNECTION"))
        _, new_local = self.start(name="new-local")
        self.assertEqual(self.session(new_local), "new-local")
        _, new_remote = self.start("100.64.0.1", name="new-remote")
        self.assertEqual(self.session(new_remote), "new-local")
        self.assertEqual(self.session(local), "seed")
        self.assertEqual(self.session(remote), "seed")

    def test_detached_candidate_is_preferred(self):
        _, local = self.start(name="first")
        self.tmux("new-session", "-d", "-s", "zzz-detached", "sleep", "300")
        _, remote = self.start("100.64.0.1", name="remote")
        self.assertEqual(self.session(remote), "zzz-detached")
        self.assertEqual(self.session(local), "seed")

    def test_unknown_source_is_conservative(self):
        _, direct = self.start(command="attach-session", name="seed", wrapped=False)
        process, known = self.start("100.64.0.1", name="known")
        self.assertEqual(self.session(known), "known")
        self.assertEqual(self.session(direct), "seed")
        output = process.received.decode()
        self.assertIn("source 100.64.0.1", output)
        self.assertIn("rejected session", output)
        self.assertIn(f"pid {direct} has unknown source", output)
        self.assertIn("no eligible existing session", output)

    def test_same_source_diagnostic_identifies_blocker_and_retained_session(self):
        _, first = self.start(name="first")
        process, second = self.start(name="second")
        self.assertEqual(self.session(first), "seed")
        self.assertEqual(self.session(second), "second")
        output = process.received.decode()
        self.assertIn(f"pid {second} source local", output)
        self.assertIn(f"pid {first} has same source local", output)
        self.assertIn("keeping session", output)
        self.assertIn("no eligible existing session", output)

    def test_syslog_reports_rejection_after_releasing_selection_lock(self):
        _, blocker = self.start(command="attach-session", name="seed", wrapped=False)
        name, created, server, pid = self.retained_client()
        name = next(line.split("\t")[0] for line in self.tmux(
            "list-clients", "-F", "#{client_name}\t#{client_pid}").splitlines()
                    if line.split("\t")[1] == pid)
        messages = []
        def receive(_priority, message):
            # Logging must not extend the selection lock's lifetime.
            with attachment.open_private(Path(self.socket).parent / f".attachment-{server}.lock") as lock:
                attachment.fcntl.flock(lock, attachment.fcntl.LOCK_EX | attachment.fcntl.LOCK_NB)
                messages.append(message)
        with mock.patch.object(attachment.syslog, "openlog"), \
             mock.patch.object(attachment.syslog, "syslog", side_effect=receive):
            status = attachment.main(["--tmux", NATIVE, "--socket", self.socket,
                                      "--client", name, "--session", created,
                                      "--server-pid", server, "--log"])
        self.assertEqual(status, 0)
        self.assertEqual(self.session(pid), "retained")
        self.assertTrue(any(f"pid {blocker} has unknown source" in line for line in messages), messages)
        self.assertTrue(any("no eligible existing session" in line for line in messages), messages)

    def test_detach_removes_live_source_and_record(self):
        first, pid = self.start(name="first")
        record = attachment.registry() / pid
        self.assertTrue(record.exists())
        first.stdin.write(b"detach-client\n")
        first.stdin.flush()
        first.communicate(timeout=5)
        self.assertFalse(record.exists())
        _, second = self.start(name="second")
        self.assertEqual(self.session(second), "seed")

    def test_explicit_switch_and_restore_creation_are_preserved(self):
        first, pid = self.start(name="first")
        first.stdin.write(b"new-session -s intentional\ndisplay-message -p finished-again\n")
        first.stdin.flush()
        self.wait_for(lambda: self.session(pid) == "intentional")
        self.tmux("set-option", "-s", attachment.DISABLE_OPTION, "1")
        _, remote = self.start("100.64.0.1", name="restored")
        self.assertEqual(self.session(remote), "restored")
        self.tmux("set-option", "-su", attachment.DISABLE_OPTION)
        self.tmux("new-session", "-d", "-s", "scripted", "sleep", "300")
        self.assertIn("scripted", self.tmux("list-sessions", "-F", "#{session_name}"))

    def test_simultaneous_same_source_clients_do_not_claim_same_session(self):
        processes = [self.start("100.64.0.1", name=f"race-{index}", wait=False)
                     for index in range(2)]
        self.wait_for(lambda: len(self.client_rows()) == 2)
        for process in processes:
            process.stdin.write(b"display-message -p finished\n")
            process.stdin.flush()
        self.wait_for(lambda: all(self.ready(process) for process in processes))
        self.assertEqual(len({row[1] for row in self.client_rows()}), 2)

    def test_configuration_reload_preserves_sources(self):
        _, first = self.start(name="first")
        self.tmux("source-file", str(self.directory / "hook.conf"))
        _, second = self.start(name="second")
        self.assertEqual(self.session(first), "seed")
        self.assertEqual(self.session(second), "second")

    def test_launcher_preserves_arguments_and_exit_status(self):
        result = subprocess.run([str(ROOT / "bin/tmux"), "-S", self.socket, "has-session",
                                 "-t", "missing"], env=self.environment, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"missing", result.stderr)

    def test_restore_modes_use_explicit_disposable_server(self):
        environment = self.environment | {"TMUX": f"{self.socket},0,0"}
        for mode in ("disable", "enable"):
            result = subprocess.run([str(ROOT / "libexec/tmux/attach-session.sh"), mode],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = self.tmux("show-option", "-sqv", attachment.DISABLE_OPTION)
            self.assertEqual(value, "1" if mode == "disable" else "")

    def test_simultaneous_distinct_sources_can_share(self):
        processes = [self.start(ip, name=f"different-{index}", wait=False)
                     for index, ip in enumerate(("100.64.0.1", "100.64.0.2"))]
        self.wait_for(lambda: len(self.client_rows()) == 2)
        for process in processes:
            process.stdin.write(b"display-message -p finished\n")
            process.stdin.flush()
        self.wait_for(lambda: all(self.ready(process) for process in processes))
        self.assertEqual({row[1] for row in self.client_rows()}, {"seed"})

    def test_unknown_incoming_client_reuses_only_detached_sessions(self):
        _, local = self.start(name="first")
        process, unknown = self.start(name="unknown", wrapped=False)
        self.assertEqual(self.session(unknown), "unknown")
        self.assertIn(f"pid {unknown} source unknown".encode(), process.received)
        self.assertIn(b"incoming source unknown; detached sessions only", process.received)
        self.tmux("new-session", "-d", "-s", "detached", "sleep", "300")
        _, other = self.start(name="unknown2", wrapped=False)
        self.assertEqual(self.session(other), "detached")
        self.assertEqual(self.session(local), "seed")

    def test_session_switch_changes_source_membership(self):
        first, pid = self.start(name="first")
        self.tmux("new-session", "-d", "-s", "destination", "sleep", "300")
        first.stdin.write(b"switch-client -t destination\n")
        first.stdin.flush()
        self.wait_for(lambda: self.session(pid) == "destination")
        _, other = self.start(name="other")
        self.assertEqual(self.session(other), "seed")

    def retained_client(self):
        self.tmux("set-option", "-s", attachment.DISABLE_OPTION, "1")
        _, pid = self.start(name="retained")
        self.tmux("set-option", "-su", attachment.DISABLE_OPTION)
        name = self.tmux("list-clients", "-F", "#{client_name}")
        created = self.tmux("display-message", "-p", "-t", "retained", "#{session_id}")
        server = self.tmux("display-message", "-p", "#{pid}")
        return name, created, server, pid

    def test_switch_failure_keeps_session_and_releases_selection_lock(self):
        name, created, server, pid = self.retained_client()
        tmux = attachment.Tmux(NATIVE, self.socket)
        original = tmux.run
        def fail_switch(*arguments):
            if arguments[0] == "switch-client":
                raise subprocess.CalledProcessError(25, arguments, stderr="switch failed")
            return original(*arguments)
        with mock.patch.object(tmux, "run", side_effect=fail_switch):
            with self.assertRaises(subprocess.CalledProcessError):
                attachment.attach(tmux, self.socket, name, created, server)
        self.assertEqual(self.session(pid), "retained")
        self.assertEqual(self.tmux("show-option", "-Av", "-t", "retained", "destroy-unattached"), "off")
        attachment.attach(tmux, self.socket, name, created, server)
        self.assertEqual(self.session(pid), "seed")

    def test_disappearing_candidate_keeps_created_session(self):
        name, created, server, pid = self.retained_client()
        tmux = attachment.Tmux(NATIVE, self.socket)
        original = tmux.run
        def delete_before_switch(*arguments):
            if arguments[0] == "switch-client":
                original("kill-session", "-t", arguments[-1])
            return original(*arguments)
        with mock.patch.object(tmux, "run", side_effect=delete_before_switch):
            attachment.attach(tmux, self.socket, name, created, server)
        self.assertEqual(self.session(pid), "retained")

    def test_renumbering_does_not_change_attachment_targets(self):
        config = self.directory / ".config/tmux"
        (config / "renumber-sessions.sh").symlink_to(ROOT / "libexec/tmux/renumber-tmux-sessions.sh")
        hooks = "\n".join(line for line in (ROOT / "config/tmux/tmux.conf").read_text().splitlines()
                          if line.startswith("set-hook -g session-created[2]")
                          or line.startswith("set-hook -g session-closed[1]"))
        file = self.directory / "renumber.conf"
        file.write_text(hooks + "\n")
        self.tmux("source-file", str(file))
        seed = self.tmux("display-message", "-p", "-t", "seed", "#{session_id}")
        self.tmux("rename-session", "-t", "seed", "7")
        _, first = self.start(name="2")
        self.wait_for(lambda: self.session(first) == "1")
        self.assertIn(seed, self.tmux("list-sessions", "-F", "#{session_id}"))
        self.assertEqual(self.session(first), "1")
        self.tmux("rename-session", "-t", "1", "7")
        _, second = self.start("100.64.0.1", name="2")
        self.wait_for(lambda: self.session(second) == "1")
        self.assertEqual(self.session(second), self.session(first))

    def test_termination_cleans_up_launcher_record(self):
        process, pid = self.start(name="first")
        process.terminate()
        process.communicate(timeout=5)
        # tmux handles SIGTERM as a graceful client detach and returns zero.
        self.assertEqual(process.returncode, 0)
        self.assertFalse((attachment.registry() / pid).exists())

    def test_killed_tmux_preserves_signal_status_and_removes_record(self):
        process, pid = self.start(name="first")
        os.kill(int(pid), signal.SIGKILL)
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, 128 + signal.SIGKILL)
        self.assertFalse((attachment.registry() / pid).exists())

    def test_killed_launcher_leaves_unknown_source(self):
        process, pid = self.start(name="first")
        record = attachment.registry() / pid
        try:
            process.kill()
            process.wait(timeout=5)
            self.assertTrue(record.exists())
            self.assertIsNone(attachment.client_source(pid))
        finally:
            # The killed supervisor cannot terminate its child or clean up.
            name = self.tmux("list-clients", "-F", "#{client_name}")
            self.tmux("detach-client", "-t", name)
            record.unlink(missing_ok=True)

    def test_interrupted_selection_releases_lock_and_keeps_session(self):
        name, created, server, pid = self.retained_client()
        tmux = attachment.Tmux(NATIVE, self.socket)
        with mock.patch.object(tmux, "candidates", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                attachment.attach(tmux, self.socket, name, created, server)
        self.assertEqual(self.session(pid), "retained")
        attachment.attach(tmux, self.socket, name, created, server)
        self.assertEqual(self.session(pid), "seed")

    def test_hook_propagates_helper_failure(self):
        helper = self.directory / ".config/tmux/attach-session.sh"
        helper.unlink()
        helper.write_text("#!/usr/bin/env python3\nraise SystemExit(37)\n")
        helper.chmod(0o755)
        process, pid = self.start(name="failed-hook")
        self.assertIn(b"returned 37", process.received)
        self.assertEqual(self.session(pid), "failed-hook")

    def test_socket_path_with_shell_characters(self):
        self.stop_server()
        self.socket = str(self.directory / "socket 'quoted $value; space")
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "seed", "sleep", "300")
        self.tmux("set-environment", "-g", "HOME", str(self.directory))
        self.tmux("source-file", str(self.directory / "hook.conf"))
        _, pid = self.start(name="new")
        self.assertEqual(self.session(pid), "seed")

    def test_terminal_suspend_and_resume_return_control_to_shell(self):
        shell_pid, terminal = pty.fork()
        if shell_pid == 0:
            os.environ.clear()
            os.environ.update(self.environment)
            os.environ["LC_ALL"] = "C"
            os.execv("/bin/bash", ["bash", "--noprofile", "--norc", "-i"])
        output = b""
        def contains(marker):
            nonlocal output
            if select.select([terminal], [], [], 0)[0]:
                output += os.read(terminal, 65536)
            return marker in output
        try:
            command = shlex.join([str(ROOT / "bin/tmux"), "-S", self.socket,
                                  "attach-session", "-t", "seed"])
            os.write(terminal, (command + "\n").encode())
            self.wait_for(lambda: bool(self.client_rows()))
            name = self.tmux("list-clients", "-F", "#{client_name}")
            self.tmux("suspend-client", "-t", name)
            self.wait_for(lambda: contains(b"Stopped"))
            os.write(terminal, b"printf 'shell-regained-control\\n'\n")
            try:
                self.wait_for(lambda: contains(b"shell-regained-control\r\n"))
            except AssertionError:
                self.fail(f"shell did not execute after suspension: {output!r}")
            os.write(terminal, b"fg\n")
            self.wait_for(lambda: "suspended" not in self.tmux(
                "list-clients", "-F", "#{client_flags}"))
            self.tmux("detach-client", "-t", name)
            os.write(terminal, b"exit\n")
            _, status = os.waitpid(shell_pid, 0)
            shell_pid = None
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        finally:
            if shell_pid is not None:
                os.kill(shell_pid, signal.SIGKILL)
                os.waitpid(shell_pid, 0)
            os.close(terminal)


if __name__ == "__main__":
    unittest.main()
