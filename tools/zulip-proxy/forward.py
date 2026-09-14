#!/usr/bin/env python3
"""Authenticate and forward one typed request from the host router."""

import os
from pathlib import Path
import socket
import struct
import sys

try:
    import typed_broker
except ImportError:  # Source-tree tests.
    import importlib.util
    path = Path(__file__).parents[1] / "codex-sandbox" / "auth-proxy" / "typed_broker.py"
    spec = importlib.util.spec_from_file_location("typed_broker", path)
    typed_broker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(typed_broker)


def exact(stream, length):
    value = bytearray()
    while len(value) < length:
        chunk = stream.read(length - len(value))
        if not chunk:
            raise RuntimeError("request ended early")
        value.extend(chunk)
    return bytes(value)


def main(arguments: list[str] | None = None) -> None:
    configured = Path(os.environ.get("SANDBOX_PROXY_SOCKET", "/run/sandbox-proxy/socket"))
    socket_path = configured if configured.exists() else Path("/run/sandbox-proxy/socket")
    token = os.environ.get("ZULIP_BROKER_KEY")
    if not token:
        raise RuntimeError("broker session token is unavailable")
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments == ["--health"]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(socket_path))
        return
    if arguments:
        raise RuntimeError("unknown forwarder argument")
    length = struct.unpack(">I", exact(sys.stdin.buffer, 4))[0]
    body = exact(sys.stdin.buffer, length)
    if sys.stdin.buffer.read(1):
        raise RuntimeError("trailing bytes after request")
    admitted = typed_broker.wrap(token, body)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(socket_path))
        connection.sendall(struct.pack(">I", len(admitted)) + admitted)
        connection.shutdown(socket.SHUT_WR)
        while chunk := connection.recv(65536):
            sys.stdout.buffer.write(chunk)


if __name__ == "__main__":
    main()
