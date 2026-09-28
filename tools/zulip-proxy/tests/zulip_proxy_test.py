from __future__ import annotations

import argparse
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
from unittest import mock
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[3]
SERVER_PATH = ROOT / "tools" / "zulip-proxy" / "server.py"
CLIENT = ROOT / "tools" / "zulip-proxy" / "client"
FORWARDER_PATH = ROOT / "tools" / "zulip-proxy" / "forward.py"
SPEC = importlib.util.spec_from_file_location("zulip_proxy", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
CLIENT_LOADER = SourceFileLoader("zulip_client", str(CLIENT))
CLIENT_SPEC = importlib.util.spec_from_loader("zulip_client", CLIENT_LOADER)
assert CLIENT_SPEC
client = importlib.util.module_from_spec(CLIENT_SPEC)
CLIENT_LOADER.exec_module(client)
FORWARDER_SPEC = importlib.util.spec_from_file_location("zulip_forward", FORWARDER_PATH)
assert FORWARDER_SPEC and FORWARDER_SPEC.loader
forwarder = importlib.util.module_from_spec(FORWARDER_SPEC)
FORWARDER_SPEC.loader.exec_module(forwarder)


def frame(value: dict) -> bytes:
    body = json.dumps(value, separators=(",", ":")).encode()
    return struct.pack(">I", len(body)) + body


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        result.extend(connection.recv(length - len(result)))
    return bytes(result)


class PackagingTest(unittest.TestCase):
    def test_proxy_image_contains_the_protocol_authority(self) -> None:
        dockerfile = (ROOT / "tools/zulip-proxy/Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "COPY tools/zulip-proxy/protocol.json /trusted/bin/protocol.json", dockerfile,
        )


class ForwarderTest(unittest.TestCase):
    def test_connects_with_a_supported_unix_socket_path(self) -> None:
        connection = mock.MagicMock()
        socket_context = mock.MagicMock()
        socket_context.__enter__.return_value = connection
        connection.recv.return_value = b""
        request = frame({"version": 1, "operation": "topics", "channel_id": 1})
        stdin = mock.Mock(buffer=io.BytesIO(request))
        stdout = mock.Mock(buffer=io.BytesIO())
        with (
            mock.patch.object(forwarder.socket, "socket", return_value=socket_context),
            mock.patch.object(forwarder.Path, "exists", return_value=True),
            mock.patch.object(forwarder.sys, "stdin", stdin),
            mock.patch.object(forwarder.sys, "stdout", stdout),
            mock.patch.dict(forwarder.os.environ, {
                "SANDBOX_PROXY_SOCKET": "/tmp/proxy", "ZULIP_BROKER_KEY": "token",
            }),
        ):
            forwarder.main([])

        connection.connect.assert_called_once_with("/tmp/proxy")
        sent = connection.sendall.call_args.args[0]
        self.assertEqual("token", json.loads(sent[4:])["token"])


    def test_health_probe_connects_without_reading_or_forwarding_a_request(self) -> None:
        connection = mock.MagicMock()
        socket_context = mock.MagicMock()
        socket_context.__enter__.return_value = connection
        with (
            mock.patch.object(forwarder.socket, "socket", return_value=socket_context),
            mock.patch.object(forwarder.Path, "exists", return_value=True),
            mock.patch.dict(forwarder.os.environ, {
                "SANDBOX_PROXY_SOCKET": "/tmp/proxy", "ZULIP_BROKER_KEY": "token",
            }),
        ):
            forwarder.main(["--health"])
        connection.connect.assert_called_once_with("/tmp/proxy")
        connection.sendall.assert_not_called()


class ServerTest(unittest.TestCase):
    def test_write_frame_retries_short_writes(self) -> None:
        class ShortWriter:
            def __init__(self) -> None:
                self.written = bytearray()
                self.flush_called = False

            def write(self, data: bytes) -> int:
                chunk = bytes(data[:3])
                self.written.extend(chunk)
                return len(chunk)

            def flush(self) -> None:
                self.flush_called = True

        writer = ShortWriter()
        body = b"a response larger than one write"

        server.write_frame(writer, body)

        self.assertEqual(struct.pack(">I", len(body)) + body, writer.written)
        self.assertTrue(writer.flush_called)

    def test_peer_disconnect_does_not_stop_server(self) -> None:
        stream = mock.Mock()
        stream.read.side_effect = OSError("peer closed")
        stream.write.side_effect = BrokenPipeError
        connection = mock.Mock()
        connection.makefile.return_value = stream

        server.serve_connection(
            connection, "http://test-zulip-caddy:8787/api/v1/messages", "session-token",
        )

    def test_accepts_only_lifecycle_caddy_endpoint(self) -> None:
        endpoint = "http://test-zulip-caddy:8787/api/v1/messages"
        self.assertEqual(endpoint, server.caddy_endpoint(endpoint))
        invalid = (
            None, "https://test-zulip-caddy:8787/api/v1/messages",
            "http://user@test-zulip-caddy:8787/api/v1/messages",
            "http://test-zulip-caddy/api/v1/messages",
            "http://test-zulip-caddy:80/api/v1/messages",
            "http://zulip.example:8787/api/v1/messages",
            "http://evil.test-zulip-caddy:8787/api/v1/messages",
            "http://Test-zulip-caddy:8787/api/v1/messages",
            "http://test-zulip-caddy:8787/api/v1/messages?x=1",
            "http://test-zulip-caddy:8787/api/v1/messages#fragment",
            "http://test-zulip-caddy:8787/api/v1/users",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(server.RequestError):
                server.caddy_endpoint(value)

    def test_framing_boundary_is_shared_with_the_client(self) -> None:
        self.assertEqual(server.PROTOCOL, client.PROTOCOL)
        body = b" " * server.MAX_REQUEST
        self.assertEqual(
            body, server.read_frame(io.BytesIO(struct.pack(">I", len(body)) + body), server.MAX_REQUEST),
        )
        oversized = body + b" "
        with self.assertRaisesRegex(server.RequestError, "too large"):
            server.read_frame(
                io.BytesIO(struct.pack(">I", len(oversized)) + oversized), server.MAX_REQUEST,
            )

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
            self.request(after="2026-02-30"),
            self.request(after="2026-04-01", before="2026-04-01"),
        ]
        for request in invalid:
            with self.subTest(request=request):
                with self.assertRaises(server.RequestError):
                    server.parse_request(json.dumps(request).encode())

    def test_authenticated_envelope_preserves_typed_request_semantics(self) -> None:
        request = self.request(topic="private")
        raw = json.dumps(request, separators=(",", ":")).encode()
        admitted = server.typed_broker.wrap("session-token", raw)
        self.assertEqual(request, server.parse_request(
            server.typed_broker.unwrap(admitted, "session-token", object_pairs_hook=server.unique_object)
        ))
        with self.assertRaises(server.typed_broker.AdmissionError):
            server.typed_broker.unwrap(admitted, "other-token")

    def test_rejects_duplicate_request_fields(self) -> None:
        with self.assertRaisesRegex(server.RequestError, "duplicate JSON field"):
            server.parse_request(
                b'{"version":1,"version":1,"channel_id":123,'
                b'"topic":null,"anchor":"oldest","include_anchor":true}'
            )

    def test_accepts_only_bounded_channel_and_topic_listing_requests(self) -> None:
        channel_request = {"version": 1, "operation": "channels"}
        self.assertEqual(channel_request, server.parse_request(json.dumps(channel_request).encode()))
        with self.assertRaises(server.RequestError):
            server.parse_request(json.dumps({**channel_request, "channel_id": 123}).encode())

        topic_request = {"version": 1, "operation": "topics", "channel_id": 123}
        self.assertEqual(topic_request, server.parse_request(json.dumps(topic_request).encode()))
        with self.assertRaises(server.RequestError):
            server.parse_request(json.dumps({**topic_request, "anchor": "oldest"}).encode())

    def test_fetches_only_fixed_get_messages_endpoint(self) -> None:
        observed = {}

        def opener(request, timeout):
            observed.update(url=request.full_url, method=request.method, timeout=timeout)
            return io.BytesIO(json.dumps({
                "result": "success", "messages": [], "found_newest": True,
            }).encode())

        result = server.fetch_page(
            "http://caddy.test/api/v1/messages",
            self.request(topic="private topic", after="2026-03-01", before="2026-04-01"), opener,
        )
        parsed = urlsplit(observed["url"])
        query = parse_qs(parsed.query)
        self.assertEqual("GET", observed["method"])
        self.assertEqual("/api/v1/messages", parsed.path)
        self.assertEqual([{"operator": "channel", "operand": 123}, {
            "operator": "topic", "operand": "private topic",
        }, {
            "operator": "sent-after", "operand": "2026-03-01",
        }, {
            "operator": "sent-before", "operand": "2026-04-01",
        }], json.loads(query["narrow"][0]))
        self.assertEqual(100, int(query["num_after"][0]))
        self.assertTrue(result["found_newest"])

    def test_fetches_only_fixed_get_channels_endpoint(self) -> None:
        observed = {}

        def opener(request, timeout):
            observed.update(url=request.full_url, method=request.method, timeout=timeout)
            return io.BytesIO(json.dumps({
                "result": "success",
                "streams": [
                    {"stream_id": 123, "name": "general", "description": "ignored"},
                ],
            }).encode())

        result = server.fetch_channels(
            "http://caddy.test/api/v1/messages",
            {"version": 1, "operation": "channels"}, opener,
        )
        self.assertEqual("GET", observed["method"])
        self.assertEqual(
            "http://caddy.test/api/v1/streams?include_can_access_content=true", observed["url"],
        )
        self.assertEqual(
            {"version": 1, "channels": [{"stream_id": 123, "name": "general"}]}, result,
        )

    def test_rejects_unsupported_channel_content_access_filter(self) -> None:
        result = {
            "result": "success",
            "streams": [],
            "ignored_parameters_unsupported": ["include_can_access_content"],
        }
        with self.assertRaisesRegex(server.RequestError, "cannot list every channel"):
            server.fetch_channels(
                "http://caddy.test/api/v1/messages",
                {"version": 1, "operation": "channels"},
                lambda request, timeout: io.BytesIO(json.dumps(result).encode()),
            )

    def test_rejects_malformed_channel_list_response(self) -> None:
        for result in ([], {"result": "success", "streams": [
            {"stream_id": True, "name": "general"},
        ]}):
            with self.subTest(result=result), self.assertRaises(server.RequestError):
                server.fetch_channels(
                    "http://caddy.test/api/v1/messages",
                    {"version": 1, "operation": "channels"},
                    lambda request, timeout: io.BytesIO(json.dumps(result).encode()),
                )

    def test_fetches_only_fixed_get_topics_endpoint(self) -> None:
        observed = {}

        def opener(request, timeout):
            observed.update(url=request.full_url, method=request.method, timeout=timeout)
            return io.BytesIO(json.dumps({
                "result": "success",
                "topics": [{"name": "private topic", "max_id": 42}],
            }).encode())

        result = server.fetch_topics(
            "http://caddy.test/api/v1/messages",
            {"version": 1, "operation": "topics", "channel_id": 123}, opener,
        )
        self.assertEqual("GET", observed["method"])
        self.assertEqual(
            "http://caddy.test/api/v1/users/me/123/topics", observed["url"],
        )
        self.assertEqual(
            {"version": 1, "topics": [{"name": "private topic", "max_id": 42}]}, result,
        )

    def test_rejects_malformed_and_unbounded_rate_limit_retries(self) -> None:
        from urllib.error import HTTPError
        request = mock.Mock()
        for retry_after in ("tomorrow", "301"):
            error = HTTPError("https://chat.example", 429, "limited",
                              {"Retry-After": retry_after}, None)
            with self.subTest(retry_after=retry_after), \
                    self.assertRaises(server.RequestError):
                server.fetch_json(request, mock.Mock(side_effect=error))

    def test_rejects_oversized_upstream_response_before_parsing(self) -> None:
        response = mock.Mock(headers={"Content-Length": str(server.MAX_RESPONSE + 1)})
        with self.assertRaisesRegex(server.RequestError, "output limit"):
            server._read_json_response(response, server.time.monotonic() + 1)
        response.read.assert_not_called()

    def test_rejects_malformed_or_non_advancing_messages(self) -> None:
        valid = {"id": 4, "timestamp": 1, "sender_full_name": "User",
                 "display_recipient": "Channel", "subject": "Topic", "content": "body"}
        self.assertEqual([valid], server.validate_messages([{**valid, "ignored": "upstream"}]))
        for messages in ([{**valid, "id": True}], [valid, dict(valid)],
                         [{**valid, "id": 4}],
                         [{key: value for key, value in valid.items() if key != "content"}]):
            with self.subTest(messages=messages), self.assertRaises(server.RequestError):
                server.validate_messages(messages, after_id=4)



class ClientTest(unittest.TestCase):
    def test_treats_closed_output_pipe_as_success(self) -> None:
        output = mock.Mock()
        output.close.side_effect = BrokenPipeError
        with mock.patch.object(client, "main", side_effect=BrokenPipeError), \
                mock.patch.object(client.sys, "stdout", output):
            self.assertEqual(0, client.entrypoint())
        output.close.assert_called_once_with()

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

    def test_validates_iso_dates(self) -> None:
        self.assertEqual("2026-03-01", client.iso_date("2026-03-01"))
        for value in ("2026-02-30", "2026-3-1", "tomorrow"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                client.iso_date(value)
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

    def test_channel_listing_rejects_channel_and_filter_arguments(self) -> None:
        for arguments in (
            ["--list-channels", "123"],
            ["--list-channels", "--list-topics"],
            ["--list-channels", "--topic", "topic"],
            ["--list-channels", "--after", "2024-01-01"],
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [str(CLIENT), *arguments], text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                self.assertEqual(125, result.returncode)
                self.assertIn("--list-channels cannot be combined", result.stderr)

    def test_channel_list_markdown_output_is_human_scannable(self) -> None:
        output = io.StringIO()
        arguments = argparse.Namespace(
            list_channels=True, channel=None, list_topics=False, topic=None,
            after=None, before=None, format="markdown",
        )
        with (
            mock.patch.object(client, "arguments", return_value=arguments),
            mock.patch.object(
                client, "request_channels",
                return_value=[{"stream_id": 123, "name": "general"}],
            ),
            mock.patch.object(client.sys, "stdout", output),
        ):
            self.assertEqual(0, client.main())
        self.assertEqual("# Zulip channels\n\n- general (ID: 123)\n", output.getvalue())

    def test_lists_channels_without_exporting_messages(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            proxy_dir = Path(temporary) / "proxies"
            socket_dir = proxy_dir / "zulip"
            socket_dir.mkdir(parents=True)
            (socket_dir / "token").write_text("test-token")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_dir / "socket"))
            listener.listen(1)
            requests = []

            def serve() -> None:
                connection, _ = listener.accept()
                with connection:
                    length = struct.unpack(">I", receive_exact(connection, 4))[0]
                    envelope = json.loads(receive_exact(connection, length))
                    self.assertEqual("test-token", envelope["token"])
                    requests.append(envelope["request"])
                    connection.recv(1)
                    connection.sendall(frame({
                        "version": 1,
                        "channels": [{"stream_id": 123, "name": "general"}],
                    }))

            thread = threading.Thread(target=serve)
            thread.start()
            result = subprocess.run(
                [str(CLIENT), "--list-channels", "--format", "jsonl"],
                env={**os.environ, "SANDBOX_PROXY_DIR": str(proxy_dir)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            thread.join(timeout=2)
            listener.close()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"stream_id": 123, "name": "general"}, json.loads(result.stdout))
        self.assertEqual([{"version": 1, "operation": "channels"}], requests)

    def test_lists_topics_without_exporting_messages(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            proxy_dir = Path(temporary) / "proxies"
            socket_dir = proxy_dir / "zulip"
            socket_dir.mkdir(parents=True)
            (socket_dir / "token").write_text("test-token")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_dir / "socket"))
            listener.listen(1)
            requests = []

            def serve() -> None:
                connection, _ = listener.accept()
                with connection:
                    length = struct.unpack(">I", receive_exact(connection, 4))[0]
                    envelope = json.loads(receive_exact(connection, length))
                    self.assertEqual("test-token", envelope["token"])
                    requests.append(envelope["request"])
                    connection.recv(1)
                    connection.sendall(frame({
                        "version": 1,
                        "topics": [{"name": "private topic", "max_id": 42}],
                    }))

            thread = threading.Thread(target=serve)
            thread.start()
            result = subprocess.run(
                [str(CLIENT), "123", "--list-topics", "--format", "jsonl"],
                env={**os.environ, "SANDBOX_PROXY_DIR": str(proxy_dir)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            thread.join(timeout=2)
            listener.close()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"name": "private topic", "max_id": 42}, json.loads(result.stdout))
        self.assertEqual(
            [{"version": 1, "operation": "topics", "channel_id": 123}], requests,
        )

    def test_paginates_and_writes_json_lines(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            proxy_dir = Path(temporary) / "proxies"
            socket_dir = proxy_dir / "zulip"
            socket_dir.mkdir(parents=True)
            (socket_dir / "token").write_text("test-token")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_dir / "socket"))
            listener.listen(2)
            requests = []

            def serve() -> None:
                for index in range(2):
                    connection, _ = listener.accept()
                    with connection:
                        length = struct.unpack(">I", receive_exact(connection, 4))[0]
                        envelope = json.loads(receive_exact(connection, length))
                        self.assertEqual("test-token", envelope["token"])
                        requests.append(envelope["request"])
                        self.assertEqual(b"", connection.recv(1))
                        response = {
                            "version": 1,
                            "messages": [{
                                "id": 40 + index, "timestamp": 1_700_000_000 + index,
                                "sender_full_name": "Example User", "display_recipient": "Channel",
                                "subject": "topic", "content": f"page {index}",
                            }],
                            "found_newest": index == 1,
                            "history_limited": index == 0,
                        }
                        connection.sendall(frame(response))

            thread = threading.Thread(target=serve)
            thread.start()
            result = subprocess.run(
                [
                    str(CLIENT), "123", "--after", "2026-03-01",
                    "--before", "2026-04-01", "--format", "jsonl",
                ],
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
            self.assertEqual("2026-03-01", requests[0]["after"])
            self.assertEqual("2026-04-01", requests[0]["before"])
            self.assertEqual(40, requests[1]["anchor"])
            self.assertFalse(requests[1]["include_anchor"])


if __name__ == "__main__":
    unittest.main()
