import errno
import json
import pty
import select
import tty
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_pi_owner import HostPiOwner, receive, send

FIXTURE = Path(__file__).with_name("host_pi_owner_fixture.py")


def connect(path, request):
    connection = socket.socket(socket.AF_UNIX)
    connection.connect(path)
    connection.settimeout(6)
    send(connection, request)
    stream = connection.makefile("rb")
    return connection, stream, receive(stream)


def request(path, value):
    connection, stream, answer = connect(path, value)
    stream.close()
    connection.close()
    return answer


def until(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError("timed out")


class StartupTerminalTest(unittest.TestCase):
    def launch(self, root, failure, terminal):
        report = root / "stdio.json"
        command = [sys.executable, str(FIXTURE), "startup", str(report), failure]
        if not terminal:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=6)
            return result.returncode, result.stderr, json.loads(report.read_text())
        master, slave = pty.openpty()
        # No line discipline transformation: test the actual emitted CR bytes.
        tty.setraw(slave)
        process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 6
        try:
            while time.monotonic() < deadline:
                if not select.select([master], [], [], .1)[0]:
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not data:
                    break
                output.extend(data)
            else:
                self.fail("startup retained terminal beyond exit")
            return process.wait(timeout=1), bytes(output), json.loads(report.read_text())
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_real_terminal_build_keeps_original_stdio_until_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output, report = self.launch(Path(directory), "ok", True)
        self.assertEqual(status, 0)
        self.assertEqual(report["before"], [True, True, True])
        self.assertEqual(report["build"], [True, True, True])
        self.assertEqual(report["startup_worker"], [False, False, False])
        self.assertEqual(report["after"], [False, False, False])
        self.assertEqual(report["worker"], [False, False, False])
        self.assertEqual(output, b"build\rready\npost-bootstrap diagnostic\n")

    def test_startup_failure_remains_visible_without_duplicate_or_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output, report = self.launch(Path(directory), "fail", True)
        self.assertEqual(status, 7)
        self.assertEqual(report["build"], [True, True, True])
        self.assertEqual(output, b"build\rready\nerror: startup failed\n")

    def test_nonterminal_startup_keeps_file_log_relay(self):
        with tempfile.TemporaryDirectory() as directory:
            status, output, report = self.launch(Path(directory), "ok", False)
        self.assertEqual(status, 0)
        self.assertEqual(report["before"], [False, False, False])
        self.assertEqual(report["startup_worker"], [False, False, False])
        self.assertEqual(report["worker"], [False, False, False])
        # Existing text-file relay normalizes carriage returns.
        self.assertEqual(output, b"build\nready\npost-bootstrap diagnostic\n")


class BootstrapReservationTest(unittest.TestCase):
    def test_slow_guest_startup_does_not_consume_original_pi_startup_budget(self):
        with mock.patch("host_pi_owner.time.monotonic", return_value=100.0) as clock:
            owner = HostPiOwner(FIXTURE, [], Path.cwd(), os.environ, timeout=30)
            connection = stream = None
            try:
                # An accepted remote workload can take longer than Pi's entire
                # startup budget before the frontend receives any launch spec.
                clock.return_value = 175.0
                owner.mark_bootstrapped()
                owner.expire()
                self.assertFalse(owner.stopping)
                owner.start()
                connection, stream, answer = connect(owner.path, {"op": "attach", "attachment": owner.original.token})
                self.assertTrue(answer["ok"])
                # If the UI itself never becomes ready, its fresh budget remains
                # bounded; guest startup has not made this reservation immortal.
                clock.return_value = 206.0
                owner.expire()
                self.assertTrue(owner.stopping)
                self.assertEqual(receive(stream)["event"], "worker-loss")
            finally:
                owner.finish(True)
                if stream is not None:
                    stream.close()
                if connection is not None:
                    connection.close()


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.session = self.root / "original.jsonl"
        self.session.write_text('{}\n')
        self.owner = HostPiOwner(FIXTURE, ["--session", str(self.session)], self.root, os.environ, timeout=.3)
        self.owner.start()
        self.connections = []

    def tearDown(self):
        self.owner.finish(True)
        for connection, stream in self.connections:
            stream.close()
            connection.close()
        self.directory.cleanup()

    def attach(self, item):
        connection, stream, answer = connect(self.owner.path, {"op": "attach", "attachment": item.token})
        self.assertTrue(answer["ok"])
        self.connections.append((connection, stream))
        return connection, stream

    def ready(self, item, session=None):
        return request(self.owner.path, {"op": "ready", "attachment": item.token,
                                         "session": str(session or self.session)})

    def test_original_closes_peer_keeps_workload_final_ack_follows_cleanup(self):
        first, first_stream = self.attach(self.owner.original)
        peer = self.owner.reserve()
        second, second_stream = self.attach(peer)
        send(first, {"op": "release"})
        self.assertEqual(receive(first_stream), {"ok": True, "final": False})
        self.assertFalse(self.owner.stopping)
        send(second, {"op": "release"})
        until(lambda: self.owner.stopping)
        second.settimeout(.1)
        with self.assertRaises(socket.timeout):
            second.recv(1)
        second.settimeout(6)
        self.owner.finish(True)
        self.assertEqual(receive(second_stream), {"ok": True, "final": True})

    def test_reservation_prevents_first_release_race_and_expires_if_launch_fails(self):
        first, stream = self.attach(self.owner.original)
        self.owner.reserve()
        send(first, {"op": "release"})
        self.assertFalse(receive(stream)["final"])
        self.assertFalse(self.owner.stopping)
        until(lambda: self.owner.stopping)

    def test_disconnected_client_drops_only_its_lease(self):
        first, stream = self.attach(self.owner.original)
        peer = self.owner.reserve()
        self.attach(peer)
        stream.close()
        first.close()
        until(lambda: self.owner.original.token not in self.owner.attachments)
        self.assertFalse(self.owner.stopping)

    def test_short_connections_are_not_leases_and_tokens_are_one_use(self):
        self.assertFalse(self.ready(self.owner.original)["ok"])
        self.attach(self.owner.original)
        self.assertTrue(self.ready(self.owner.original)["ok"])
        self.assertEqual(len(self.owner.attachments), 1)
        self.assertFalse(request(self.owner.path, {"op": "attach", "attachment": self.owner.original.token})["ok"])
        self.assertFalse(request(self.owner.path, {"op": "ready", "attachment": "invented", "session": str(self.session)})["ok"])

    def test_side_rejects_other_session_directory_without_reserving(self):
        self.owner.environment.update(TMUX="fixture", TMUX_PANE="%0")
        self.attach(self.owner.original)
        self.ready(self.owner.original)
        outside = self.root / "elsewhere"
        outside.mkdir()
        foreign = outside / "snapshot.jsonl"
        foreign.write_text('{}\n')
        answer = request(self.owner.path, {"op": "side", "attachment": self.owner.original.token, "session": str(foreign)})
        self.assertFalse(answer["ok"])
        self.assertIn("session directory", answer["error"])
        self.assertEqual(len(self.owner.attachments), 1)

    def test_ready_accepts_lazy_session_file_and_ephemeral_session_directory(self):
        self.attach(self.owner.original)
        lazy = self.root / "not-published-yet.jsonl"
        self.assertTrue(self.ready(self.owner.original, lazy)["ok"])
        self.assertFalse(lazy.exists())
        self.assertTrue(request(self.owner.path, {"op": "ready", "attachment": self.owner.original.token,
                                                 "session": None, "sessionDir": str(self.root)})["ok"])
        self.assertEqual(self.owner.original.session_directory, self.root)
        switched = self.root / "custom-session-dir"
        switched.mkdir()
        self.assertTrue(self.ready(self.owner.original, switched / "new-lazy.jsonl")["ok"])
        self.assertEqual(self.owner.original.session_directory, switched)
        self.assertTrue(request(self.owner.path, {"op": "ready", "attachment": self.owner.original.token,
                                                 "session": None, "sessionDir": str(self.root)})["ok"])
        self.assertEqual(self.owner.original.session_directory, self.root)

    def test_editor_target_falls_back_only_to_live_admitted_pane(self):
        targets = []
        self.owner.pane_changed = targets.append
        self.owner.original.pane = "%1"
        first, stream = self.attach(self.owner.original)
        self.ready(self.owner.original)
        peer = self.owner.reserve()
        peer.pane = "%2"
        second, peer_stream = self.attach(peer)
        self.ready(peer)
        reserved = self.owner.reserve()
        reserved.pane = "%3"
        send(first, {"op": "release"})
        self.assertFalse(receive(stream)["final"])
        self.assertEqual(targets[-1], "%2")
        send(second, {"op": "release"})
        self.assertFalse(receive(peer_stream)["final"])
        self.assertIsNone(targets[-1])

    def test_worker_loss_notifies_all_lifetime_connections(self):
        _, first = self.attach(self.owner.original)
        _, second = self.attach(self.owner.reserve())
        self.owner.worker_lost()
        for stream in (first, second):
            self.assertEqual(receive(stream)["event"], "worker-loss")


@unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
class ProcessAndTmuxTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = "owner-test-" + uuid.uuid4().hex
        result = subprocess.run(["tmux", "-L", self.server, "new-session", "-d", "-P", "-F", "#{pane_id}",
                                 "sleep 120"], capture_output=True, text=True)
        if result.returncode:
            self.directory.cleanup()
            self.skipTest(result.stderr)
        self.pane = result.stdout.strip()
        tmux = subprocess.check_output(["tmux", "-L", self.server, "display-message", "-p",
                                        "#{socket_path},#{pid},0"], text=True).strip()
        self.environment = dict(os.environ, TMUX=tmux, TMUX_PANE=self.pane,
                                HOST_OWNER_SECRET="accepted-secret-must-not-reach-tmux-argv")
        self.processes = []
        self.sockets = []

    def tearDown(self):
        for connection, stream in self.sockets:
            stream.close()
            connection.close()
        subprocess.run(["tmux", "-L", self.server, "kill-server"], capture_output=True)
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait()
        self.directory.cleanup()

    def launch(self, *, exit_zero_on_term=False):
        original = self.root / "original.jsonl"
        original.write_text('{}\n')
        marker = self.root / "cleaned"
        pidfile = self.root / "worker"
        process = subprocess.Popen([sys.executable, str(FIXTURE), "launcher", str(original), str(marker), str(pidfile)],
                                   env=dict(self.environment, **({"FIXTURE_TERM_EXIT_ZERO": "1"} if exit_zero_on_term else {})),
                                   cwd=self.root, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE if exit_zero_on_term else subprocess.DEVNULL)
        self.processes.append(process)
        until(original.with_suffix(".ready").exists)
        info = json.loads(original.with_suffix(".ready").read_text())
        return process, info, original, marker, pidfile

    def side(self, info):
        snapshot = self.root / "copied.jsonl"
        snapshot.write_text('{}\n')
        answer = request(info["owner"], {"op": "side", "attachment": info["attachment"], "session": str(snapshot)})
        self.assertTrue(answer["ok"], answer)
        until(snapshot.with_suffix(".ready").exists)
        clone = json.loads(snapshot.with_suffix(".ready").read_text())
        self.assertEqual(info["owner"], clone["owner"])
        self.assertEqual(clone["sentinel"], self.environment["HOST_OWNER_SECRET"])
        self.assertEqual(clone["cwd"], str(self.root))
        self.assertEqual(clone["pane"], answer["pane"])
        self.assertNotIn("ORIGINAL_PROMPT", clone["argv"])
        directory_index = clone["argv"].index("--session-dir")
        self.assertEqual(clone["argv"][directory_index + 1], str(snapshot.parent))
        self.assertNotIn("obsolete-directory", " ".join(clone["argv"]))
        pane_command = subprocess.check_output(["tmux", "-L", self.server, "display-message", "-p", "-t",
                                                answer["pane"], "#{pane_start_command}"], text=True)
        self.assertNotIn(self.environment["HOST_OWNER_SECRET"], pane_command)
        return snapshot, clone, answer["pane"]

    def test_detached_owner_survives_original_sigkill_and_hup(self):
        for signum in (signal.SIGKILL, signal.SIGHUP):
            with self.subTest(signal=signum):
                process, info, original, marker, pidfile = self.launch()
                snapshot, clone, pane = self.side(info)
                process.send_signal(signum)
                process.wait(timeout=6)
                time.sleep(.2)
                self.assertFalse(marker.exists(), "first pane exit cleaned peer workload")
                os.kill(int(pidfile.read_text()), 0)
                self.assertTrue(request(clone["owner"], {"op": "ready", "attachment": clone["attachment"], "session": str(snapshot)})["ok"])
                snapshot.with_suffix(".exit").touch()
                until(marker.exists)
                until(lambda: not Path(info["owner"]).exists())
                for file in self.root.iterdir():
                    file.unlink()

    def test_normal_first_exit_preserves_side_and_clone_can_side_after_original_pane_dies(self):
        process, info, original, marker, pidfile = self.launch()
        snapshot, clone, pane = self.side(info)
        original.with_suffix(".exit").touch()
        self.assertEqual(process.wait(timeout=6), 0)
        self.assertFalse(marker.exists())
        subprocess.run(["tmux", "-L", self.server, "kill-pane", "-t", self.pane], check=True)
        next_snapshot = self.root / "second-copy.jsonl"
        next_snapshot.write_text('{}\\n')
        answer = request(clone["owner"], {"op": "side", "attachment": clone["attachment"], "session": str(next_snapshot)})
        self.assertTrue(answer["ok"], answer)
        snapshot.with_suffix(".exit").touch()
        time.sleep(.2)
        self.assertFalse(marker.exists())
        next_snapshot.with_suffix(".exit").touch()
        until(marker.exists)

    def test_failed_frontend_exec_releases_reservation_without_waiting_deadline(self):
        original = self.root / "original.jsonl"
        original.write_text('{}\\n')
        marker = self.root / "cleaned"
        environment = dict(self.environment, FIXTURE_BAD_WRAPPER="1")
        process = subprocess.Popen([sys.executable, str(FIXTURE), "launcher", str(original), str(marker), str(self.root / "worker")],
                                   env=environment, cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        self.assertEqual(process.wait(timeout=2), 1)
        self.assertTrue(marker.exists())

    def test_malformed_cd_request_releases_only_invoking_wrapper_without_deadlock(self):
        process, info, original, marker, pidfile = self.launch()
        snapshot, clone, pane = self.side(info)
        original.with_suffix(".handoff").write_text("partial-json-request")
        self.assertEqual(process.wait(timeout=3), 1)
        self.assertFalse(marker.exists())
        self.assertTrue(request(clone["owner"], {"op": "ready", "attachment": clone["attachment"], "session": str(snapshot)})["ok"])
        snapshot.with_suffix(".exit").touch()
        until(marker.exists)

    def test_worker_loss_native_exit_zero_reports_loss_not_deleted_cd_file(self):
        process, info, original, marker, pidfile = self.launch(exit_zero_on_term=True)
        snapshot, clone, pane = self.side(info)
        os.kill(int(pidfile.read_text()), signal.SIGKILL)
        self.assertEqual(process.wait(timeout=6), 1)
        _, stderr = process.communicate(timeout=1)
        self.assertEqual(stderr.decode().strip(), "error: guest tool worker stopped")
        until(marker.exists)
        until(lambda: not Path(info["owner"]).exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(clone["pid"], 0)

    def test_real_worker_loss_interrupts_original_and_side(self):
        process, info, original, marker, pidfile = self.launch()
        snapshot, clone, pane = self.side(info)
        os.kill(int(pidfile.read_text()), signal.SIGKILL)
        self.assertEqual(process.wait(timeout=6), 1)
        until(marker.exists)
        until(lambda: not Path(info["owner"]).exists())
        # A pane can remain in tmux with remain-on-exit; its Pi process may not.
        with self.assertRaises(ProcessLookupError):
            os.kill(clone["pid"], 0)

    def test_failed_side_removes_only_created_pane_and_original_remains_usable(self):
        process, info, original, marker, pidfile = self.launch()
        snapshot = self.root / "copied.jsonl"
        snapshot.write_text('fail-readiness')
        # A real wrapper attaches, its native child exits before ready, and the
        # controller must kill only the pane created for that failed launch.
        before = subprocess.check_output(["tmux", "-L", self.server, "list-panes", "-F", "#{pane_id}"], text=True)
        answer = request(info["owner"], {"op": "side", "attachment": info["attachment"], "session": str(snapshot)})
        self.assertFalse(answer["ok"])
        after = subprocess.check_output(["tmux", "-L", self.server, "list-panes", "-F", "#{pane_id}"], text=True)
        self.assertEqual(before, after)
        self.assertFalse(marker.exists())
        self.assertTrue(request(info["owner"], {"op": "ready", "attachment": info["attachment"], "session": str(original)})["ok"])
        original.with_suffix(".exit").touch()
        self.assertEqual(process.wait(timeout=6), 0)
        until(marker.exists)


if __name__ == "__main__":
    unittest.main()
