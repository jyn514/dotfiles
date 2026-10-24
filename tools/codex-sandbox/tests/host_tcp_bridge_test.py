import errno
import socket
import struct
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_tcp_bridge import FixedTcpBridge


class FixedTcpBridgeTest(unittest.TestCase):
    def test_selected_loopback_service_is_relayed_only_after_peer_admission(self) -> None:
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen(2)
            bridge = FixedTcpBridge(target.getsockname())
            bridge.start()
            try:
                # The availability probe is the first connection.
                target.accept()[0].close()
                with socket.create_connection(("127.0.0.1", bridge.port)) as rejected:
                    self.assertEqual(b"", rejected.recv(1))
                bridge.allow_peers({"127.0.0.1"})

                def respond() -> None:
                    with target.accept()[0] as connection:
                        self.assertEqual(b"request", connection.recv(7))
                        connection.sendall(b"response")

                worker = threading.Thread(target=respond)
                worker.start()
                with socket.create_connection(("127.0.0.1", bridge.port)) as client:
                    client.sendall(b"request")
                    self.assertEqual(b"response", client.recv(8))
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
            finally:
                bridge.stop()

    def test_half_close_preserves_large_response_and_reverse_half_close(self) -> None:
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen(2)
            bridge = FixedTcpBridge(target.getsockname())
            self.addCleanup(bridge.stop)
            bridge.allow_peers({"127.0.0.1"})
            bridge.start()
            target.accept()[0].close()
            payload = b"response" * 50000
            received = []
            errors = []

            def respond():
                try:
                    with target.accept()[0] as connection:
                        connection.settimeout(3)
                        # Upstream EOF must not prevent request bytes travelling
                        # in the other direction before downstream's own EOF.
                        connection.sendall(payload)
                        connection.shutdown(socket.SHUT_WR)
                        data = bytearray()
                        while chunk := connection.recv(65536):
                            data.extend(chunk)
                        received.append(bytes(data))
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=respond)
            worker.start()
            with socket.create_connection(("127.0.0.1", bridge.port), timeout=3) as client:
                data = bytearray()
                while chunk := client.recv(65536):
                    data.extend(chunk)
                client.sendall(b"after-response-EOF")
                client.shutdown(socket.SHUT_WR)
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(payload, data)
            self.assertEqual([b"after-response-EOF"], received)

    def test_downstream_request_eof_does_not_drop_broker_response(self) -> None:
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen(2)
            bridge = FixedTcpBridge(target.getsockname())
            self.addCleanup(bridge.stop)
            bridge.allow_peers({"127.0.0.1"})
            bridge.start()
            target.accept()[0].close()
            received = []
            request_eof = threading.Event()
            release_response = threading.Event()

            def respond():
                with target.accept()[0] as connection:
                    connection.settimeout(3)
                    data = bytearray()
                    while chunk := connection.recv(65536):
                        data.extend(chunk)
                    received.append(bytes(data))
                    request_eof.set()
                    if not release_response.wait(timeout=3):
                        raise AssertionError("response release missing")
                    connection.sendall(b"framed response after EOF")

            worker = threading.Thread(target=respond)
            worker.start()
            with socket.create_connection(("127.0.0.1", bridge.port), timeout=3) as client:
                client.sendall(b"request")
                client.shutdown(socket.SHUT_WR)
                self.assertTrue(request_eof.wait(timeout=3))
                # Keep both directions quiet across several bridge selector
                # ticks: ordinary framing EOF is not transport cancellation.
                time.sleep(0.5)
                release_response.set()
                data = bytearray()
                while chunk := client.recv(65536):
                    data.extend(chunk)
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
            self.assertEqual([b"request"], received)
            self.assertEqual(b"framed response after EOF", data)

    def test_stop_interrupts_backpressure_in_either_direction_and_disconnect(self) -> None:
        for direction in ("response", "request", "disconnect"):
            with self.subTest(direction=direction), socket.socket() as target:
                target.bind(("127.0.0.1", 0))
                target.listen(2)
                bridge = FixedTcpBridge(target.getsockname())
                self.addCleanup(bridge.stop)
                bridge.allow_peers({"127.0.0.1"})
                bridge.start()
                target.accept()[0].close()
                with socket.create_connection(("127.0.0.1", bridge.port), timeout=3) as client:
                    upstream, _ = target.accept()
                    with upstream:
                        blocked = upstream if direction == "response" else client
                        blocked.setblocking(False)
                        # More than kernel socket buffers; stop cannot depend on
                        # the unreading opposite endpoint becoming writable.
                        for _ in range(20000):
                            try:
                                blocked.send(b"x" * 65536)
                            except BlockingIOError:
                                break
                        if direction == "disconnect":
                            client.close()
                        started = time.monotonic()
                        bridge.stop()
                        self.assertLess(time.monotonic() - started, 2.5)
                        with bridge.workers_lock:
                            self.assertFalse(bridge.workers)
                        with bridge.connections_lock:
                            self.assertFalse(bridge.connections)

    def test_abortive_close_after_eof_is_visible_without_response_traffic(self) -> None:
        # Prove the TCP primitive independently of the bridge: normal write EOF
        # followed by an abortive full close still produces a later SO_ERROR.
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen(1)
            with socket.create_connection(target.getsockname(), timeout=3) as client:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                with target.accept()[0] as upstream:
                    upstream.settimeout(3)
                    client.sendall(b"strict request")
                    client.shutdown(socket.SHUT_WR)
                    self.assertEqual(b"strict request", upstream.recv(65536))
                    self.assertEqual(b"", upstream.recv(1))
                    client.close()
                    error = 0
                    until = time.monotonic() + 2
                    while not error and time.monotonic() < until:
                        error = upstream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        time.sleep(0.01)
                    # Linux reports EPIPE after request EOF was consumed.
                    self.assertIn(error, (errno.EPIPE, errno.ECONNRESET))

    def test_bridge_propagates_later_reset_after_eof_while_response_is_quiet(self) -> None:
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen(2)
            bridge = FixedTcpBridge(target.getsockname())
            self.addCleanup(bridge.stop)
            bridge.allow_peers({"127.0.0.1"})
            bridge.start()
            target.accept()[0].close()
            with socket.create_connection(("127.0.0.1", bridge.port), timeout=3) as client:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                client.sendall(b"strict request")
                client.shutdown(socket.SHUT_WR)
                with target.accept()[0] as upstream:
                    upstream.settimeout(3)
                    data = bytearray()
                    while chunk := upstream.recv(65536):
                        data.extend(chunk)
                    self.assertEqual(b"strict request", data)
                    # The broker is executing and has no response pending. The
                    # bridge must notice cancellation without a read/write event
                    # on its already half-closed downstream request direction.
                    client.close()
                    error = 0
                    until = time.monotonic() + 2
                    while not error and time.monotonic() < until:
                        error = upstream.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        time.sleep(0.01)
                    self.assertIn(error, (errno.EPIPE, errno.ECONNRESET))
                    until = time.monotonic() + 2
                    while time.monotonic() < until:
                        with bridge.workers_lock:
                            if not bridge.workers:
                                break
                        time.sleep(0.01)
                    with bridge.workers_lock:
                        self.assertFalse(bridge.workers)

    def test_explicit_private_listener_allows_peers_but_bounds_active_connections(self) -> None:
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen(4)
            target.settimeout(2)
            bridge = FixedTcpBridge(target.getsockname(), listen_address=("127.0.0.1", 0),
                                    allow_all_peers=True, max_connections=2)
            self.addCleanup(bridge.stop)
            bridge.start()
            target.accept()[0].close()
            clients = []
            upstreams = []
            try:
                for _ in range(2):
                    client = socket.create_connection(("127.0.0.1", bridge.port), timeout=2)
                    client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    clients.append(client)
                    upstreams.append(target.accept()[0])
                with socket.create_connection(("127.0.0.1", bridge.port), timeout=2) as excess:
                    try:
                        self.assertEqual(b"", excess.recv(1))
                    except ConnectionResetError:
                        pass
                target.settimeout(0.3)
                with self.assertRaises(TimeoutError):
                    target.accept()
                with bridge.workers_lock:
                    self.assertEqual(2, len(bridge.workers))
                for client in clients:
                    client.close()
                until = time.monotonic() + 2
                while time.monotonic() < until:
                    with bridge.workers_lock:
                        if not bridge.workers:
                            break
                    time.sleep(0.01)
                with bridge.workers_lock:
                    self.assertFalse(bridge.workers)
                target.settimeout(2)
                with socket.create_connection(("127.0.0.1", bridge.port), timeout=2) as fresh:
                    with target.accept()[0] as upstream:
                        fresh.sendall(b"capacity released")
                        self.assertEqual(b"capacity released", upstream.recv(64))
            finally:
                for connection in clients + upstreams:
                    connection.close()

    def test_invalid_private_capacity_rejects_before_any_listener(self) -> None:
        with self.assertRaises(ValueError):
            FixedTcpBridge(("127.0.0.1", 1), max_connections=0)

    def test_unavailable_required_service_is_not_published(self) -> None:
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            target = reserved.getsockname()
        bridge = FixedTcpBridge(target)
        with self.assertRaises(OSError):
            bridge.start()
        self.assertIsNone(bridge.listener)


if __name__ == "__main__":
    unittest.main()
