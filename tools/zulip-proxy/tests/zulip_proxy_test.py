from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[3]
SERVER_PATH = ROOT / "tools" / "zulip-proxy" / "server.py"
CLIENT = ROOT / "tools" / "zulip-proxy" / "client"
SPEC = importlib.util.spec_from_file_location("zulip_proxy", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
CLIENT_LOADER = SourceFileLoader("zulip_client", str(CLIENT))
CLIENT_SPEC = importlib.util.spec_from_loader("zulip_client", CLIENT_LOADER)
assert CLIENT_SPEC
client = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_LOADER.exec_module(client)


def frame(value: dict) -> bytes:
    body = json.dumps(value, separators=(",", ":")).encode()
    return struct.pack(">I", len(body)) + body


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        result.extend(connection.recv(length - len(result)))
    return bytes(result)


class ServerTest(unittest.TestCase):
    def request(self, **updates: object) -> dict:
        request = {
            "version": 1,
            "channel_id": 123,
            "topic": None,
            "anchor": "oldest",
            "include_anchor": True,
        }
        request.update(updates)
        return request

    def test_rejects_fields_and_operands_outside_read_only_protocol(self) -> None:
        invalid = [
            self.request(operation="send"),
            self.request(channel_id="general"),
            self.request(anchor="newest"),
            self.request(topic="bad\nheader"),
            self.request(include_anchor=1),
        ]
        for request in invalid:
            with self.subTest(request=request):
                with self.assertRaises(server.RequestError):
                    server.parse_request(json.dumps(request).encode())

    def test_rejects_duplicate_request_fields(self) -> None:
        with self.assertRaisesRegex(server.RequestError, "duplicate JSON field"):
            server.parse_request(
                b'{"version":1,"version":1,"channel_id":123,'
                b'"topic":null,"anchor":"oldest","include_anchor":true}'
            )

    def test_fetches_only_fixed_get_messages_endpoint(self) -> None:
        observed = {}

        def opener(request, timeout):
            observed.update(url=request.full_url, method=request.method,
                            authorization=request.headers["Authorization"], timeout=timeout)
            return io.BytesIO(json.dumps({
                "result": "success", "messages": [], "found_newest": True,
            }).encode())

        result = server.fetch_page(
            "https://chat.example.test/api/v1/messages", "credential",
            self.request(topic="private topic"), opener,
        )
        parsed = urlsplit(observed["url"])
        query = parse_qs(parsed.query)
        self.assertEqual("GET", observed["method"])
        self.assertEqual("/api/v1/messages", parsed.path)
        self.assertEqual("Basic credential", observed["authorization"])
        self.assertEqual([{"operator": "channel", "operand": 123}, {
            "operator": "topic", "operand": "private topic",
        }], json.loads(query["narrow"][0]))
        self.assertEqual(100, int(query["num_after"][0]))
        self.assertTrue(result["found_newest"])

    def test_rejects_non_https_or_credentialed_site(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            path = Path(temporary) / "zuliprc"
            for site in ("http://chat.example.test", "https://key@chat.example.test"):
                path.write_text(
                    f"[api]\nsite={site}\nemail=user@example.test\nkey=secret\n",
                    encoding="utf-8",
                )
                with self.subTest(site=site), self.assertRaises(server.RequestError):
                    server.load_credentials(path)


class ClientTest(unittest.TestCase):
    def test_parses_numeric_channel_and_narrow_urls(self) -> None:
        self.assertEqual((123, None), client.parse_channel("123", None))
        self.assertEqual(
            (456, "private/topic"),
            client.parse_channel(
                "https://rust-lang.zulipchat.com/#narrow/channel/456-secret/"
                "topic/private.2Ftopic/near/789",
                None,
            ),
        )
        self.assertEqual(
            (456, None),
            client.parse_channel(
                "https://rust-lang.zulipchat.com/#narrow/channel/456-secret/near/789",
                None,
            ),
        )

    def test_rejects_invalid_or_conflicting_narrow_urls(self) -> None:
        invalid = [
            "https://rust-lang.zulipchat.com/#narrow/channel/no-id",
            "https://rust-lang.zulipchat.com/#narrow/dm/123",
            "https://rust-lang.zulipchat.com/#narrow/channel/123-name/search/query",
            "https://rust-lang.zulipchat.com/#narrow/channel/123-name/topic/bad.GG",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                client.parse_channel(value, None)
        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            client.parse_channel(
                "https://rust-lang.zulipchat.com/#narrow/channel/123-name/topic/one",
                "two",
            )

    def test_host_wrapper_shows_help_without_an_active_proxy(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin/zulip"), "--help"],
            env={key: value for key, value in os.environ.items() if key != "SANDBOX_PROXY_DIR"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("numeric channel ID or Zulip narrow URL", result.stdout)

    def test_reports_when_proxy_is_unavailable_in_active_sandbox(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as proxy_dir:
            result = subprocess.run(
                [str(CLIENT), "123", "--format", "jsonl"],
                env={**os.environ, "SANDBOX_PROXY_DIR": proxy_dir},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        self.assertEqual(125, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("proxy 'zulip' is unavailable", result.stderr)
        self.assertIn("restart the sandbox", result.stderr)

    def test_paginates_and_writes_json_lines(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            proxy_dir = Path(temporary) / "proxies"
            socket_dir = proxy_dir / "zulip"
            socket_dir.mkdir(parents=True)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_dir / "socket"))
            listener.listen(2)
            requests = []

            def serve() -> None:
                for index in range(2):
                    connection, _ = listener.accept()
                    with connection:
                        length = struct.unpack(">I", receive_exact(connection, 4))[0]
                        requests.append(json.loads(receive_exact(connection, length)))
                        self.assertEqual(b"", connection.recv(1))
                        response = {
                            "version": 1,
                            "messages": [{"id": 40 + index, "content": f"page {index}"}],
                            "found_newest": index == 1,
                            "history_limited": index == 0,
                        }
                        connection.sendall(frame(response))

            thread = threading.Thread(target=serve)
            thread.start()
            result = subprocess.run(
                [str(CLIENT), "123", "--format", "jsonl"],
                env={**os.environ, "SANDBOX_PROXY_DIR": str(proxy_dir)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            thread.join(timeout=2)
            listener.close()
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("history limits omitted older messages", result.stderr)
            self.assertEqual([40, 41], [json.loads(line)["id"] for line in result.stdout.splitlines()])
            self.assertEqual("oldest", requests[0]["anchor"])
            self.assertTrue(requests[0]["include_anchor"])
            self.assertEqual(40, requests[1]["anchor"])
            self.assertFalse(requests[1]["include_anchor"])


if __name__ == "__main__":
    unittest.main()
