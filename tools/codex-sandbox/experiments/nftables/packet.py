"""Owned namespace peer and UDP/raw-Ethernet probes; never contacts the host."""

import argparse
import ipaddress
import socket
import struct
import sys


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('hold', 'listen', 'send'))
    parser.add_argument('--address')
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--mac')
    parser.add_argument('--source', default='203.0.113.99')
    args = parser.parse_args()
    if args.mode == 'hold':
        print('ready', flush=True)
        sys.stdin.read()
        return
    family = socket.AF_INET6 if args.address and ':' in args.address else socket.AF_INET
    if args.mode == 'listen':
        with socket.socket(family, socket.SOCK_DGRAM) as server:
            server.bind((args.address or '0.0.0.0', args.port))
            server.settimeout(0.7)
            print('ready', flush=True)
            try:
                data, _ = server.recvfrom(1024)
            except TimeoutError:
                raise SystemExit(1)
            if data != b'nft-probe':
                raise SystemExit('unexpected packet')
        return
    if not args.mac:
        with socket.socket(family, socket.SOCK_DGRAM) as client:
            client.sendto(b'nft-probe', (args.address, args.port))
        return
    # Send to a selected Ethernet next hop, independently of the namespace routes.
    # This catches source-IP checks and same-interface routing mistaken for bridging.
    source = ipaddress.IPv4Address(args.source).packed
    destination = ipaddress.IPv4Address(args.address).packed
    udp = struct.pack('!HHHH', 23456, args.port, 17, 0) + b'nft-probe'
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), 123, 0, 64, 17, 0,
                         source, destination)
    header = header[:10] + struct.pack('!H', checksum(header)) + header[12:]
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW) as client:
        client.bind(('eth0', 0))
        ethernet = bytes.fromhex(args.mac.replace(':', '')) + client.getsockname()[4]
        client.send(ethernet + b'\x08\x00' + header + udp)


if __name__ == '__main__':
    main()
