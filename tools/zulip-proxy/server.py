#!/usr/bin/env python3
"""Serve a narrow, read-only subset of the Zulip API over a Unix socket."""

from __future__ import annotations

import base64
import configparser
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


SOCKET = Path("/run/sandbox-proxy/socket")
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
    fields = {"version", "channel_id", "topic", "anchor", "include_anchor"}
    if not isinstance(request, dict) or set(request) != fields:
        raise RequestError("request has missing or unknown fields")
    if request["version"] != 1:
        raise RequestError("unsupported protocol version")
    channel_id = request["channel_id"]
    if isinstance(channel_id, bool) or not isinstance(channel_id, int) or channel_id <= 0:
        raise RequestError("channel_id must be a positive integer")
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
    while True:
        try:
            with opener(http_request, timeout=60) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code != 429:
                raise RequestError(f"Zulip returned HTTP {error.code}") from error
            time.sleep(min(int(error.headers.get("Retry-After", "10")), 300))
    if result.get("result") != "success" or not isinstance(result.get("messages"), list):
        raise RequestError(result.get("msg", "Zulip returned a malformed response"))
    return {
        "version": 1,
        "messages": result["messages"],
        "found_newest": result.get("found_newest") is True,
        "history_limited": result.get("history_limited") is True,
    }


def process_request(body: bytes, endpoint: str, authorization: str) -> bytes:
    try:
        request = parse_request(body)
        response = fetch_page(endpoint, authorization, request)
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
