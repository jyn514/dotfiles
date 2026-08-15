#!/usr/bin/env python3
"""Serve a narrow, read-only subset of the Zulip API over a Unix socket."""

from __future__ import annotations

import base64
import configparser
from datetime import date
import json
import os
from pathlib import Path
import socket
import struct
import time
from typing import Any, BinaryIO, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request as HttpRequest


SOCKET = Path(os.environ.get("SANDBOX_PROXY_SOCKET", "/run/sandbox-proxy/socket"))
CONFIG = Path("/run/secrets/zuliprc")
MAX_REQUEST = 16 << 10
MAX_RESPONSE = 16 << 20


class RequestError(Exception):
    pass


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise RequestError("Zulip API redirected the credentialed request")


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


def load_credentials(path: Path = CONFIG) -> tuple[str, str]:
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise RequestError(f"cannot read credentials from {path}")
    try:
        api = parser["api"]
        site = api["site"].rstrip("/")
        credential = f"{api['email']}:{api['key']}".encode()
    except KeyError as error:
        raise RequestError(f"missing {error} in zuliprc [api] section") from error
    parsed = urlsplit(site)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RequestError("zuliprc site must be a plain HTTPS server URL")
    authorization = base64.b64encode(credential).decode("ascii")
    return f"{site}/api/v1/messages", authorization


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
    if request["version"] != 1:
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


def fetch_page(
    endpoint: str,
    authorization: str,
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
        headers={"Authorization": f"Basic {authorization}"},
        method="GET",
    )
    result = fetch_json(http_request, opener)
    if result.get("result") != "success" or not isinstance(result.get("messages"), list):
        raise RequestError(result.get("msg", "Zulip returned a malformed response"))
    return {
        "version": 1,
        "messages": result["messages"],
        "found_newest": result.get("found_newest") is True,
        "history_limited": result.get("history_limited") is True,
    }


def fetch_json(http_request: HttpRequest, opener: Callable[..., Any]) -> Any:
    while True:
        try:
            with opener(http_request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429:
                raise RequestError(f"Zulip returned HTTP {error.code}") from error
            time.sleep(min(int(error.headers.get("Retry-After", "10")), 300))


def fetch_topics(
    endpoint: str,
    authorization: str,
    request: dict[str, Any],
    opener: Callable[..., Any] = URL_OPEN,
) -> dict[str, Any]:
    topics_endpoint = endpoint.removesuffix("/messages")
    http_request = HttpRequest(
        f"{topics_endpoint}/users/me/{request['channel_id']}/topics",
        headers={"Authorization": f"Basic {authorization}"},
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
        "version": 1,
        "topics": [{"name": topic["name"], "max_id": topic["max_id"]} for topic in topics],
    }


def process_request(body: bytes, endpoint: str, authorization: str) -> bytes:
    try:
        request = parse_request(body)
        response = (
            fetch_topics(endpoint, authorization, request)
            if request.get("operation") == "topics"
            else fetch_page(endpoint, authorization, request)
        )
    except (OSError, RequestError, ValueError, json.JSONDecodeError) as error:
        response = {"version": 1, "error": str(error)}
    body = json.dumps(response, separators=(",", ":")).encode()
    if len(body) > MAX_RESPONSE:
        body = json.dumps({
            "version": 1, "error": "Zulip response exceeds the proxy output limit",
        }, separators=(",", ":")).encode()
    return body


def serve_connection(connection: socket.socket, endpoint: str, authorization: str) -> None:
    stream = connection.makefile("rwb", buffering=0)
    try:
        body = read_frame(stream, MAX_REQUEST)
    except (OSError, RequestError) as error:
        body = json.dumps({"version": 1, "error": str(error)}, separators=(",", ":")).encode()
    else:
        body = process_request(body, endpoint, authorization)
    write_frame(stream, body)


def main() -> None:
    endpoint, authorization = load_credentials()
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
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
                serve_connection(connection, endpoint, authorization)
                next_api_request = time.monotonic() + 2


if __name__ == "__main__":
    main()
