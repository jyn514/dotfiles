#!/usr/bin/env python3
"""Forward one framed request between the host router and proxy socket."""

import shutil
import socket
import sys


def main() -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect("/run/sandbox-proxy/socket")
        shutil.copyfileobj(sys.stdin.buffer, connection.makefile("wb", buffering=0))
        connection.shutdown(socket.SHUT_WR)
        shutil.copyfileobj(connection.makefile("rb", buffering=0), sys.stdout.buffer)


if __name__ == "__main__":
    main()
