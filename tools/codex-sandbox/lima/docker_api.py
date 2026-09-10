"""Read metadata from the recorded Docker socket without CLI startup."""

import http.client
import json
import socket
import subprocess


def inspect(socket_path, path, command):
    connection = http.client.HTTPConnection('localhost', timeout=10)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(10)
    try:
        connection.sock.connect(socket_path)
        connection.request('GET', path)
        response = connection.getresponse()
        data = json.loads(response.read())
        if not isinstance(data, dict):
            raise ValueError('Docker inspection did not return an object')
        if response.status != 200:
            raise subprocess.CalledProcessError(1, command, stderr=data.get('message', str(response.status)))
        return data
    finally:
        connection.close()
