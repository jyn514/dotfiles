#!/usr/bin/env python3
"""Forward one framed request between the host router and proxy socket."""

import os
from pathlib import Path
import shutil
import socket
import sys


def main() -> None:
    configured = Path(os.environ.get("SANDBOX_PROXY_SOCKET", "/run/sandbox-proxy/socket"))
    socket_path = configured if configured.exists() else Path("/run/sandbox-proxy/socket")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(socket_path)
        shutil.copyfileobj(sys.stdin.buffer, connection.makefile("wb", buffering=0))
        connection.shutdown(socket.SHUT_WR)
        shutil.copyfileobj(connection.makefile("rb", buffering=0), sys.stdout.buffer)


if __name__ == "__main__":
    main()
