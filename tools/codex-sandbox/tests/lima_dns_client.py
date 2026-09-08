"""Exercise DNS and denied transports from inside an unprivileged workload."""

import errno
from pathlib import Path
import socket
import struct
import sys


def receive(sock, count):
    data = bytearray()
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise AssertionError("truncated DNS response")
        data.extend(part)
    return bytes(data)


def main():
    mode, address = sys.argv[1:]
    servers = [line.split()[1] for line in Path("/etc/resolv.conf").read_text().splitlines()
               if line.split()[:1] == ["nameserver"]]
    # Nerdctl prepends RootlessKit DNS even when --dns specifies the same IP.
    if set(servers) != {address}:
        raise AssertionError(f"unexpected workload resolvers: {servers}")
    if mode == "denied":
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            for port in (22, 54, 80, 443):
                with socket.socket(socket.AF_INET, kind) as sock:
                    sock.settimeout(3)
                    try:
                        sock.connect((address, port))
                        sock.send(b"blocked-port-probe")
                    except OSError as error:
                        if error.errno != errno.EACCES:
                            raise AssertionError(f"expected policy denial, got {error}") from error
                    else:
                        raise AssertionError(f"unrestricted access to {address}:{port}")
        print("TCP/UDP non-DNS ports denied by policy")
        return
    kind = {"tcp": socket.SOCK_STREAM, "udp": socket.SOCK_DGRAM}[mode]
    # One ordinary A query, framed separately for TCP. Validate the transaction
    # and successful answer, without pinning a public site's changing addresses.
    query = struct.pack("!6H", 0x5342, 0x0100, 1, 0, 0, 0) + b"\x07example\x03com\0" + struct.pack("!HH", 1, 1)
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.settimeout(5)
        sock.connect((address, 53))
        if mode == "tcp":
            sock.sendall(struct.pack("!H", len(query)) + query)
            response = receive(sock, struct.unpack("!H", receive(sock, 2))[0])
        else:
            sock.send(query)
            response = sock.recv(4096)
    transaction, flags, questions, answers, _, _ = struct.unpack("!6H", response[:12])
    if transaction != 0x5342 or not flags & 0x8000 or flags & 0x000f or questions != 1 or not answers:
        raise AssertionError("invalid or unsuccessful DNS response")
    print(mode + " DNS query succeeded")


if __name__ == "__main__":
    main()
