"""Read metadata from the recorded Docker socket without CLI startup."""

import http.client
import json
import socket
import subprocess
from urllib.parse import urlencode


class APIError(subprocess.CalledProcessError):
    def __init__(self, status, command, message):
        super().__init__(1, command, stderr=message)
        self.status = status


def request(socket_path, method, path, command, *, payload=None, expected=(200,)):
    connection = http.client.HTTPConnection('localhost', timeout=10)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(10)
    try:
        connection.sock.connect(socket_path)
        body = None if payload is None else json.dumps(payload).encode()
        headers = {} if body is None else {'Content-Type': 'application/json'}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise ValueError('Docker API did not return an object')
        if response.status not in expected:
            raise APIError(response.status, command, data.get('message', str(response.status)))
        return data
    finally:
        connection.close()


def inspect(socket_path, path, command):
    return request(socket_path, 'GET', path, command)


def hijack(socket_path, path, command, *, query=None):
    """Open one Docker upgraded HTTP stream and retain its response reader."""
    target = path
    if query:
        target += '?' + urlencode(query)
    transport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    transport.settimeout(10)
    try:
        transport.connect(socket_path)
        request_bytes = (
            f'POST {target} HTTP/1.1\r\n'
            'Host: localhost\r\n'
            'Connection: Upgrade\r\n'
            'Upgrade: tcp\r\n'
            'Content-Length: 0\r\n\r\n'
        ).encode('ascii')
        transport.sendall(request_bytes)
        response = transport.makefile('rb', buffering=0)
        status_line = response.readline(4096)
        fields = status_line.decode('ascii', errors='replace').rstrip('\r\n').split(' ', 2)
        if len(fields) < 2 or not fields[0].startswith('HTTP/') or not fields[1].isdigit():
            raise ValueError('Docker API returned an invalid upgrade response')
        status = int(fields[1])
        headers = {}
        while True:
            line = response.readline(65536)
            if line in (b'\r\n', b'\n'):
                break
            if not line:
                raise ValueError('Docker API ended inside upgrade headers')
            name, separator, value = line.partition(b':')
            if not separator:
                raise ValueError('Docker API returned an invalid upgrade header')
            headers[name.strip().lower()] = value.strip()
        if status != 101:
            length = headers.get(b'content-length', b'0')
            raw = response.read(int(length)) if length.isdigit() else b''
            try:
                data = json.loads(raw) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {}
            message = data.get('message', str(status)) if isinstance(data, dict) else str(status)
            raise APIError(status, command, message)
        transport.settimeout(None)
        return transport, response
    except BaseException:
        transport.close()
        raise
