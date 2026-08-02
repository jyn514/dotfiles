from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "libexec" / "agent-wrappers" / "jj-proxy-client"


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        result.extend(connection.recv(length - len(result)))
    return bytes(result)


class JjProxyClientTest(unittest.TestCase):
    def test_forwards_cwd_arguments_and_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            current = repository / "nested"
            current.mkdir(parents=True)
            socket_directory = root / "proxies" / "jj"
            socket_directory.mkdir(parents=True)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_directory / "socket"))
            listener.listen(1)
            request: dict = {}

            def serve() -> None:
                connection, _ = listener.accept()
                with connection:
                    length = struct.unpack(">I", receive_exact(connection, 4))[0]
                    request.update(json.loads(receive_exact(connection, length)))
                    response = json.dumps({
                        "version": 1, "exit": 7, "stdout": "output\n", "stderr": "warning\n",
                    }).encode()
                    connection.sendall(struct.pack(">I", len(response)) + response)

            server = threading.Thread(target=serve)
            server.start()
            environment = {
                **os.environ,
                "SANDBOX_PROXY_DIR": str(root / "proxies"),
                "JJ_PROXY_REPO": str(repository),
                "JJ_USER": "Codex gpt-test",
                "JJ_EMAIL": "codex@example.test",
            }
            result = subprocess.run(
                [str(CLIENT), "status", "--quiet"], cwd=current, env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            server.join(timeout=2)
            listener.close()
            self.assertEqual(7, result.returncode)
            self.assertEqual("output\n", result.stdout)
            self.assertEqual("warning\n", result.stderr)
            self.assertEqual({
                "version": 1,
                "cwd": "nested",
                "argv": ["status", "--quiet"],
                "user": "Codex gpt-test",
                "email": "codex@example.test",
            }, request)


if __name__ == "__main__":
    unittest.main()
