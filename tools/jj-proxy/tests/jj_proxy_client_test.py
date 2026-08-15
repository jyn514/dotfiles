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


ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "tools" / "jj-proxy" / "client"


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        result.extend(connection.recv(length - len(result)))
    return bytes(result)


class JjProxyClientTest(unittest.TestCase):
    def run_client(self, arguments: list[str], *, files: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            current = repository / "nested"
            current.mkdir(parents=True)
            for name, contents in (files or {}).items():
                (repository / name).write_text(contents)
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
            expanded = [str(repository / argument.removeprefix("REPO/")) if argument.startswith("REPO/") else argument for argument in arguments]
            result = subprocess.run(
                [str(CLIENT), *expanded], cwd=current, env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            server.join(timeout=2)
            listener.close()
            return result, request

    def test_forwards_cwd_arguments_and_response(self) -> None:
        result, request = self.run_client(["status", "--quiet"])

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

    def test_encodes_agent_split_as_a_dedicated_operation(self) -> None:
        patch = "diff --git a/note b/note\n--- a/note\n+++ b/note\n"
        result, request = self.run_client(
            ["--agent-split", "REPO/selected.patch", "Extract note", "@"],
            files={"selected.patch": patch},
        )

        self.assertEqual(7, result.returncode)
        self.assertEqual([], request["argv"])
        self.assertEqual({
            "patch": patch,
            "message": "Extract note",
            "revision": "@",
        }, request["agent_split"])


if __name__ == "__main__":
    unittest.main()
