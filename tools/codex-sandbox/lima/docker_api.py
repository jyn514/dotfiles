"""Read metadata from the recorded Docker socket without CLI startup."""

import http.client
import json
import socket
import subprocess


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
