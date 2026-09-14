"""Listener ownership must survive partial gateway creation."""
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gateway

TRANSPORT = runpy.run_path(str(Path(__file__).resolve().parents[3] / "libexec/agent-wrappers/gateway-transport"))


class GatewayTransportTest(unittest.TestCase):
    def test_delayed_listener_succeeds_before_one_deadline(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        address = listener.getsockname()
        listener.close()

        def start_later():
            time.sleep(0.15)
            with socket.socket() as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(address); server.listen(1)
                connection, _ = server.accept(); connection.close()

        worker = threading.Thread(target=start_later)
        worker.start()
        connection = TRANSPORT["connect_until"](address, time.monotonic() + 1)
        connection.close(); worker.join()

    def test_connected_relay_outlives_connection_attempt_timeout(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0)); server.listen(1)
            local, client = socket.socketpair()
            failures = []

            def delayed_server():
                connection, _ = server.accept()
                with connection:
                    self.assertEqual(b"request", connection.recv(7))
                    # Longer than the connect attempt's remaining timeout.
                    time.sleep(0.3)
                    connection.sendall(b"response")
                    connection.shutdown(socket.SHUT_WR)

            responder = threading.Thread(target=delayed_server)
            responder.start()
            upstream = TRANSPORT["connect_until"](
                server.getsockname(), time.monotonic() + 0.1,
            )
            self.assertIsNone(upstream.gettimeout())

            def run_relay():
                try:
                    TRANSPORT["relay"](local, upstream)
                except BaseException as error:
                    failures.append(error)

            worker = threading.Thread(target=run_relay)
            worker.start()
            client.sendall(b"request"); client.shutdown(socket.SHUT_WR)
            self.assertEqual(b"response", client.recv(8))
            client.close(); worker.join(); responder.join()
            local.close(); upstream.close()
            self.assertEqual([], failures)

    def test_permanent_failure_stops_at_deadline(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); address = probe.getsockname()
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            TRANSPORT["connect_until"](address, started + 0.2)
        self.assertLess(time.monotonic() - started, 0.6)

    def test_interruption_is_not_retried(self):
        with patch.object(TRANSPORT["socket"], "create_connection", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                TRANSPORT["connect_until"](("127.0.0.1", 1), time.monotonic() + 1)

    def test_accept_returns_child_exit_status_without_waiting_for_connection(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
            self.assertIsNone(TRANSPORT["accept_before_deadline"](
                listener, child, time.monotonic() + 2,
            ))
            self.assertEqual(7, child.wait())

    def test_accept_uses_invocation_deadline(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            child = Mock(); child.poll.return_value = None
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                TRANSPORT["accept_before_deadline"](listener, child, started + 0.15)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_accept_interruption_is_terminal(self):
        listener = Mock(); child = Mock(); child.poll.return_value = None
        selector = Mock()
        selector.__enter__ = Mock(return_value=selector)
        selector.__exit__ = Mock(return_value=False)
        selector.select.side_effect = InterruptedError
        with patch.object(TRANSPORT["selectors"], "DefaultSelector", return_value=selector):
            with self.assertRaises(InterruptedError):
                TRANSPORT["accept_before_deadline"](listener, child, time.monotonic() + 1)
        selector.select.assert_called_once()

    def test_native_ssh_configuration_forces_host_key_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); (home / ".ssh").mkdir()
            command = TRANSPORT["force_verified_native_ssh"](
                home, 4321, ["/usr/local/bin/podman", "info"],
            )
            config = (home / ".ssh/config").read_text(encoding="utf-8")
        self.assertEqual(["/usr/local/bin/podman", "--ssh=native", "info"], command)
        self.assertIn("StrictHostKeyChecking yes", config)
        self.assertIn("UserKnownHostsFile ", config)
        self.assertIn("Port 4321", config)

    def test_relay_send_failure_does_not_call_connection_retry(self):
        left = Mock(); right = Mock()
        left.recv.side_effect = [b"request"]
        right.sendall.side_effect = OSError("ambiguous send")
        fake_selector = Mock()
        fake_selector.select.return_value = [(Mock(fileobj=left, data=right), None)]
        with patch.object(TRANSPORT["selectors"], "DefaultSelector", return_value=fake_selector):
            with self.assertRaisesRegex(OSError, "ambiguous send"):
                TRANSPORT["relay"](left, right)
        right.sendall.assert_called_once_with(b"request")


class GatewayTest(unittest.TestCase):
    def test_second_listener_spawn_failure_reaps_the_first(self):
        popen = subprocess.Popen
        children = []

        def spawn(_command, **kwargs):
            if children:
                raise OSError('second listener failed')
            child = popen(['sleep', '300'], **kwargs)
            children.append(child)
            return child

        with patch.object(gateway.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaisesRegex(OSError, 'second listener failed'):
                gateway.serve('host.lima.internal', 1234, 5678)
        self.assertIsNotNone(children[0].poll())
        with self.assertRaises(ProcessLookupError):
            os.killpg(children[0].pid, 0)

    def test_nested_listener_does_not_require_editor(self):
        child = Mock(pid=12, returncode=None)
        with patch.object(gateway.subprocess, 'Popen', return_value=child) as spawn, \
                patch.object(gateway.os, 'wait', return_value=(12, 0)), \
                patch.object(gateway.os, 'killpg'):
            self.assertEqual(1, gateway.serve('host.lima.internal', podman_port=22))
        self.assertIn('TCP4-LISTEN:2222,fork,reuseaddr', spawn.call_args.args[0])

    def test_empty_gateway_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least one listener'):
            gateway.serve('host.lima.internal')


if __name__ == '__main__':
    unittest.main()
