#!/usr/bin/env python3
"""Serve a narrow, read-only subset of the Zulip API over a Unix socket."""

from __future__ import annotations

from datetime import date
import json
import os
import re
from pathlib import Path
import socket
import struct
import time
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request as HttpRequest


SOCKET = Path(os.environ.get("SANDBOX_PROXY_SOCKET", "/run/sandbox-proxy/socket"))
with Path(__file__).with_name("protocol.json").open(encoding="utf-8") as stream:
    PROTOCOL = json.load(stream)
PROTOCOL_VERSION = PROTOCOL["version"]
MAX_REQUEST = PROTOCOL["max_request_bytes"]
MAX_RESPONSE = PROTOCOL["max_response_bytes"]
SESSION_KEY = os.environ.get("ZULIP_BROKER_KEY")
CADDY_ENDPOINT = os.environ.get("ZULIP_CADDY_ENDPOINT")
try:
    import typed_broker
except ImportError:  # Source-tree tests.
    import importlib.util
    _path = Path(__file__).parents[1] / "codex-sandbox" / "auth-proxy" / "typed_broker.py"
    _spec = importlib.util.spec_from_file_location("typed_broker", _path)
    typed_broker = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(typed_broker)


class RequestError(Exception):
    pass


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise RequestError("Zulip API redirected the request")


URL_OPEN = build_opener(RejectRedirects()).open


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def read_exact(stream: BinaryIO, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = stream.read(length - len(result))
        if not chunk:
            raise RequestError("request ended early")
        result.extend(chunk)
    return bytes(result)


def read_frame(stream: BinaryIO, limit: int) -> bytes:
    length = struct.unpack(">I", read_exact(stream, 4))[0]
    if length > limit:
        raise RequestError("request is too large")
    body = read_exact(stream, length)
    if stream.read(1):
        raise RequestError("trailing bytes after request")
    return body


def write_frame(stream: BinaryIO, body: bytes) -> None:
    if len(body) > MAX_RESPONSE:
        raise RequestError("response is too large")
    stream.write(struct.pack(">I", len(body)) + body)
    stream.flush()


def parse_request(body: bytes) -> dict[str, Any]:
    try:
        request = json.loads(body, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RequestError("request is not valid UTF-8 JSON") from error
    if not isinstance(request, dict):
        raise RequestError("request has missing or unknown fields")
    operation = request.get("operation", "messages")
    fields = {"version", "operation", "channel_id"}
    message_fields = {"version", "channel_id", "topic", "anchor", "include_anchor"}
    if operation != "topics":
        fields = set(request)
        if not message_fields <= fields or fields - message_fields - {"after", "before"}:
            raise RequestError("request has missing or unknown fields")
    if operation == "topics" and set(request) != fields:
        raise RequestError("request has missing or unknown fields")
    if request["version"] != PROTOCOL_VERSION:
        raise RequestError("unsupported protocol version")
    channel_id = request["channel_id"]
    if isinstance(channel_id, bool) or not isinstance(channel_id, int) or channel_id <= 0:
        raise RequestError("channel_id must be a positive integer")
    if operation == "topics":
        return request
    for field in ("after", "before"):
        if field in request:
            value = request[field]
            if not isinstance(value, str):
                raise RequestError(f"{field} must be an ISO date")
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as error:
                raise RequestError(f"{field} must be an ISO date") from error
            if parsed_date.isoformat() != value:
                raise RequestError(f"{field} must be an ISO date")
    if request.get("after") and request.get("before") and request["after"] >= request["before"]:
        raise RequestError("after must be earlier than before")
    topic = request["topic"]
    if topic is not None and (
        not isinstance(topic, str)
        or len(topic.encode()) > 1024
        or any(character in topic for character in "\0\r\n")
    ):
        raise RequestError("topic must be a bounded single-line string or null")
    anchor = request["anchor"]
    if not (
        anchor == "oldest"
        or isinstance(anchor, int) and not isinstance(anchor, bool) and anchor > 0
    ):
        raise RequestError("anchor must be 'oldest' or a positive message ID")
    if not isinstance(request["include_anchor"], bool):
        raise RequestError("include_anchor must be boolean")
    return request


def validate_messages(messages: Any, after_id: int = 0) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        raise RequestError("Zulip returned malformed message data")
    previous = after_id
    fields = {"id", "timestamp", "sender_full_name", "display_recipient", "subject", "content"}
    required_strings = ("sender_full_name", "display_recipient", "subject", "content")
    for message in messages:
        if (not isinstance(message, dict) or not fields <= set(message) or
                isinstance(message.get("id"), bool) or
                not isinstance(message.get("id"), int) or message["id"] <= previous or
                isinstance(message.get("timestamp"), bool) or
                not isinstance(message.get("timestamp"), int) or message["timestamp"] < 0 or
                not all(isinstance(message.get(field), str) for field in required_strings)):
            raise RequestError("Zulip returned malformed or unordered message data")
        previous = message["id"]
    return [{field: message[field] for field in (
        "id", "timestamp", "sender_full_name", "display_recipient", "subject", "content",
    )} for message in messages]


def fetch_page(
    endpoint: str,
    request: dict[str, Any],
    opener: Callable[..., Any] = URL_OPEN,
) -> dict[str, Any]:
    narrow: list[dict[str, Any]] = [
        {"operator": "channel", "operand": request["channel_id"]},
    ]
    if request["topic"] is not None:
        narrow.append({"operator": "topic", "operand": request["topic"]})
    for field in ("after", "before"):
        if field in request:
            narrow.append({"operator": f"sent-{field}", "operand": request[field]})
    query = urlencode({
        "anchor": request["anchor"],
        "include_anchor": json.dumps(request["include_anchor"]),
        "num_before": 0,
        "num_after": 100,
        "apply_markdown": "false",
        "allow_empty_topic_name": "true",
        "narrow": json.dumps(narrow, separators=(",", ":")),
    })
    http_request = HttpRequest(
        f"{endpoint}?{query}",
        method="GET",
    )
    result = fetch_json(http_request, opener)
    if result.get("result") != "success":
        raise RequestError(result.get("msg", "Zulip returned a malformed response"))
    messages = validate_messages(
        result.get("messages"), request["anchor"] if isinstance(request["anchor"], int) else 0,
    )
    return {
        "version": PROTOCOL_VERSION,
        "messages": messages,
        "found_newest": result.get("found_newest") is True,
        "history_limited": result.get("history_limited") is True,
    }


def _read_json_response(response: Any, deadline: float) -> Any:
    raw_length = getattr(response, "headers", {}).get("Content-Length")
    if raw_length is not None:
        if not raw_length.isascii() or not raw_length.isdecimal():
            raise RequestError("Zulip returned malformed response framing")
        if int(raw_length) > MAX_RESPONSE:
            raise RequestError("Zulip response exceeds the proxy output limit")
    body = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RequestError("Zulip response deadline expired")
        connection = getattr(response, "connection", None)
        sock = getattr(connection, "sock", None)
        if sock is not None:
            sock.settimeout(min(60, remaining))
        chunk = response.read(min(64 * 1024, MAX_RESPONSE + 1 - len(body)))
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > MAX_RESPONSE:
            raise RequestError("Zulip response exceeds the proxy output limit")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RequestError("Zulip returned malformed JSON") from error


def fetch_json(http_request: HttpRequest, opener: Callable[..., Any]) -> Any:
    deadline = time.monotonic() + 300
    attempts = 0
    while attempts < 5:
        attempts += 1
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestError("Zulip rate-limit retry deadline expired")
            with opener(http_request, timeout=min(60, remaining)) as response:
                return _read_json_response(response, deadline)
        except HTTPError as error:
            if error.code != 429:
                raise RequestError(f"Zulip returned HTTP {error.code}") from error
            value = error.headers.get("Retry-After", "10")
            if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
                raise RequestError("Zulip returned invalid Retry-After") from error
            delay = int(value)
            remaining = deadline - time.monotonic()
            if delay > 300 or delay > remaining or attempts >= 5:
                raise RequestError("Zulip rate limit exceeded retry bounds") from error
            time.sleep(delay)
    raise RequestError("Zulip rate limit exceeded retry attempts")


def fetch_topics(
    endpoint: str,
    request: dict[str, Any],
    opener: Callable[..., Any] = URL_OPEN,
) -> dict[str, Any]:
    topics_endpoint = endpoint.removesuffix("/messages")
    http_request = HttpRequest(
        f"{topics_endpoint}/users/me/{request['channel_id']}/topics",
        method="GET",
    )
    result = fetch_json(http_request, opener)
    topics = result.get("topics")
    if result.get("result") != "success" or not isinstance(topics, list):
        raise RequestError(result.get("msg", "Zulip returned a malformed response"))
    if any(
        not isinstance(topic, dict)
        or not isinstance(topic.get("name"), str)
        or isinstance(topic.get("max_id"), bool)
        or not isinstance(topic.get("max_id"), int)
        for topic in topics
    ):
        raise RequestError("Zulip returned malformed topic data")
    return {
        "version": PROTOCOL_VERSION,
        "topics": [{"name": topic["name"], "max_id": topic["max_id"]} for topic in topics],
    }


def process_request(body: bytes, endpoint: str) -> bytes:
    try:
        request = parse_request(body)
        response = (
            fetch_topics(endpoint, request)
            if request.get("operation") == "topics"
            else fetch_page(endpoint, request)
        )
    except (OSError, RequestError, ValueError, json.JSONDecodeError) as error:
        response = {"version": PROTOCOL_VERSION, "error": str(error)}
    body = json.dumps(response, separators=(",", ":")).encode()
    if len(body) > MAX_RESPONSE:
        body = json.dumps({
            "version": PROTOCOL_VERSION, "error": "Zulip response exceeds the proxy output limit",
        }, separators=(",", ":")).encode()
    return body


def serve_connection(connection: socket.socket, endpoint: str,
                     session_key: str | None = SESSION_KEY) -> None:
    stream = connection.makefile("rwb", buffering=0)
    try:
        body = read_frame(stream, MAX_REQUEST + 512)
        if not session_key:
            raise RequestError("broker session token is unavailable")
        try:
            body = typed_broker.unwrap(body, session_key, object_pairs_hook=unique_object)
            if len(body) > MAX_REQUEST:
                raise RequestError("request is too large")
        except typed_broker.AdmissionError as error:
            raise RequestError(str(error)) from error
    except (OSError, RequestError) as error:
        body = json.dumps({
            "version": PROTOCOL_VERSION, "error": str(error),
        }, separators=(",", ":")).encode()
    else:
        body = process_request(body, endpoint)
    write_frame(stream, body)


def caddy_endpoint(value: str | None) -> str:
    if not value:
        raise RequestError("ZULIP_CADDY_ENDPOINT must not be empty")
    parsed = urlsplit(value)
    hostname = parsed.hostname
    valid_hostname = (
        isinstance(hostname, str)
        and len(hostname) <= 63
        and hostname.endswith("-zulip-caddy")
        and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname) is not None
    )
    try:
        port = parsed.port
    except ValueError as error:
        raise RequestError("ZULIP_CADDY_ENDPOINT must name the fixed Caddy messages route") from error
    if (parsed.scheme != "http" or not valid_hostname or port != 8787
            or parsed.netloc != f"{hostname}:8787"
            or parsed.username is not None or parsed.password is not None
            or parsed.path != "/api/v1/messages" or parsed.query or parsed.fragment):
        raise RequestError("ZULIP_CADDY_ENDPOINT must name the fixed Caddy messages route")
    return value


def main() -> None:
    endpoint = caddy_endpoint(CADDY_ENDPOINT)
    global URL_OPEN
    URL_OPEN = build_opener(RejectRedirects()).open
    if not SESSION_KEY:
        raise RequestError("ZULIP_BROKER_KEY must not be empty")
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    token_path = SOCKET.parent / "token"
    token_path.write_text(SESSION_KEY, encoding="ascii")
    os.chmod(token_path, 0o400)
    SOCKET.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(SOCKET))
        os.chmod(SOCKET, 0o666)
        listener.listen(8)
        next_api_request = 0.0
        while True:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(70)
                time.sleep(max(0.0, next_api_request - time.monotonic()))
                serve_connection(connection, endpoint, SESSION_KEY)
                next_api_request = time.monotonic() + 2


if __name__ == "__main__":
    main()
