"""Network assertions inside an owned Docker test container (or its VM/host)."""

import socket
import struct
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def assert_http_200(target, *, timeout=10):
    """Allow server startup, but require a complete HTTP response, not TCP accept."""
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    error = None
    while time.monotonic() < deadline:
        try:
            with opener.open('http://' + target, timeout=min(3, deadline - time.monotonic())) as response:
                assert response.status == 200, (target, response.status)
                response.read()
            return
        except (OSError, URLError) as failure:
            error = failure
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise AssertionError(f'no completed HTTP 200 from {target} within {timeout}s') from error


def main(argv=None):
    mode, target = sys.argv[1:] if argv is None else argv
    if mode == 'http':
        assert_http_200(target)
    elif mode == 'dns-tcp':
        query = (struct.pack('!HHHHHH', 0x5342, 0x0100, 1, 0, 0, 0) +
                 b'\x07example\x03com\0' + struct.pack('!HH', 1, 1))
        with socket.create_connection((target, 53), timeout=5) as connection:
            connection.sendall(struct.pack('!H', len(query)) + query)
            stream = connection.makefile('rb')
            size, = struct.unpack('!H', stream.read(2))
            response = stream.read(size)
            assert len(response) == size and size >= 12
            identity, flags, _, answers, _, _ = struct.unpack('!HHHHHH', response[:12])
            assert identity == 0x5342 and flags & 0x8000 and flags & 15 == 0 and answers
    elif mode == 'public':
        assert socket.getaddrinfo('example.com', 80)
        with build_opener(ProxyHandler({})).open('http://example.com', timeout=10) as response:
            assert response.status == 200
        try:
            socket.create_connection(('2606:4700:4700::1111', 80), timeout=2)
        except OSError:
            pass
        else:
            raise AssertionError('IPv6 egress is enabled')
    else:
        address, port = target.rsplit(':', 1)
        deadline = time.monotonic() + (10 if mode == 'allow' else 0)
        while True:
            try:
                with socket.create_connection((address, int(port)), timeout=3):
                    connected = True
            except OSError:
                connected = False
            if connected or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        assert connected == (mode == 'allow'), (mode, target, connected)
    print('PASS:', mode, target)


if __name__ == '__main__':
    main()
