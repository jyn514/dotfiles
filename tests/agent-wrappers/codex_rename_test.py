import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import unittest


COMMAND = Path(__file__).resolve().parents[2] / "libexec/agent-wrappers/codex-rename"


def read_exact(connection, size):
    result = b""
    while len(result) < size:
        data = connection.recv(size - len(result))
        if not data:
            raise EOFError
        result += data
    return result


def read_frame(connection):
    first, second = read_exact(connection, 2)
    size = second & 127
    if size == 126:
        size = struct.unpack("!H", read_exact(connection, 2))[0]
    elif size == 127:
        size = struct.unpack("!Q", read_exact(connection, 8))[0]
    if not second & 128:
        raise AssertionError("client WebSocket frames must be masked")
    mask = read_exact(connection, 4)
    data = read_exact(connection, size)
    return first & 15, bytes(value ^ mask[i % 4] for i, value in enumerate(data))


def send_frame(connection, data, opcode=1, final=True):
    size = len(data)
    header = bytes([(128 if final else 0) | opcode])
    if size < 126:
        header += bytes([size])
    else:
        header += bytes([126]) + struct.pack("!H", size)
    connection.sendall(header + data)


class CodexRenameTest(unittest.TestCase):
    def run_command(self, directory, title, thread_id="owned-session"):
        environment = {**os.environ, "CODEX_HOME": str(directory)}
        environment.pop("CODEX_THREAD_ID", None)
        if thread_id:
            environment["CODEX_THREAD_ID"] = thread_id
        return subprocess.run([str(COMMAND), title], env=environment,
                              text=True, capture_output=True, timeout=5)

    def exercise_daemon(self, title="rename π " + "x" * 150, failure=None):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "app-server-control/app-server-control.sock"
            target.parent.mkdir()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(target))
                listener.listen()
                listener.settimeout(3)
                requests = []

                def serve():
                    with listener.accept()[0] as connection:
                        connection.settimeout(3)
                        header = b""
                        while b"\r\n\r\n" not in header:
                            header += connection.recv(4096)
                        key = next(line.split(b":", 1)[1].strip() for line in header.split(b"\r\n")
                                   if line.lower().startswith(b"sec-websocket-key:"))
                        accept = base64.b64encode(hashlib.sha1(
                            key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                        ).digest())
                        connection.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                                           b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
                        name = "old title"
                        try:
                            while True:
                                opcode, data = read_frame(connection)
                                if opcode == 10:
                                    self.assertEqual(b"ping", data)
                                    continue
                                request = json.loads(data)
                                requests.append(request)
                                method = request["method"]
                                if method == "initialized":
                                    continue
                                if method == "initialize":
                                    result = {}
                                elif method == "thread/name/set":
                                    self.assertEqual("owned-session", request["params"]["threadId"])
                                    name = request["params"]["name"]
                                    if failure == "disconnect":
                                        return
                                    result = {}
                                elif method == "thread/read":
                                    self.assertEqual("owned-session", request["params"]["threadId"])
                                    result = {"thread": {"name": "stale" if failure == "mismatch" else name}}
                                else:
                                    self.fail(f"unexpected method: {method}")
                                response = {"id": request["id"], "result": result}
                                if failure == "read-error" and method == "thread/read":
                                    response = {"id": request["id"], "error": {"message": "session missing"}}
                                # Exercise ping handling, notifications, and fragmented responses.
                                send_frame(connection, b"ping", opcode=9)
                                send_frame(connection, b'{"method":"thread/name/updated","params":{}}')
                                payload = json.dumps(response).encode()
                                send_frame(connection, payload[:10], final=False)
                                send_frame(connection, payload[10:], opcode=0)
                        except EOFError:
                            pass

                with ThreadPoolExecutor(max_workers=1) as executor:
                    server = executor.submit(serve)
                    result = self.run_command(home, title)
                    server.result(timeout=4)
            return result, requests

    def test_renames_current_session_and_verifies_unicode_long_title(self):
        result, requests = self.exercise_daemon()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("(verified)", result.stdout)
        self.assertEqual(["initialize", "initialized", "thread/read", "thread/name/set", "thread/read"],
                         [request["method"] for request in requests])
        self.assertIn("rename π", result.stdout)

    def test_failed_read_does_not_send_name_update(self):
        result, requests = self.exercise_daemon(failure="read-error")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("session missing", result.stderr)
        self.assertIn("name update was not sent", result.stderr)
        self.assertNotIn("thread/name/set", [request["method"] for request in requests])

    def test_mismatching_read_back_reports_unverified_update(self):
        result, _ = self.exercise_daemon(failure="mismatch")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("read-back name differs", result.stderr)
        self.assertIn("name update is unverified", result.stderr)

    def test_disconnect_during_update_does_not_claim_success(self):
        result, _ = self.exercise_daemon(failure="disconnect")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("name update is unverified", result.stderr)

    def test_missing_session_id_and_invalid_titles_fail_before_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_command(directory, "title", thread_id=None)
            self.assertIn("CODEX_THREAD_ID is unset", result.stderr)
            self.assertEqual(2, result.returncode)
            for title in ("", "\nmultiline", "  "):
                result = self.run_command(directory, title)
                self.assertEqual(2, result.returncode)
                self.assertIn("nonempty single line", result.stderr)

    def test_missing_daemon_reports_no_update_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_command(directory, "title")
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("connecting to the Codex daemon failed", result.stderr)
        self.assertIn("name update was not sent", result.stderr)
        self.assertIn("check the running Codex daemon", result.stderr)


if __name__ == "__main__":
    unittest.main()
