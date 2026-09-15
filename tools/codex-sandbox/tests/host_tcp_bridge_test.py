import socket
from pathlib import Path
import sys
import threading
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
