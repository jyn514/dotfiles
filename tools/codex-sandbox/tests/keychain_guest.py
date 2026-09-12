"""Exercise the R2 relay from a disposable container, using dummy credentials."""

import json
import os
import socket
import struct

host, port = os.environ['CODEX_SANDBOX_KEYCHAIN_ADDRESS'].rsplit(':', 1)
for token, status in [('wrong', 'unavailable'), (os.environ['CODEX_SANDBOX_KEYCHAIN_TOKEN'], 'ok')]:
    with socket.create_connection((host, int(port)), timeout=10) as connection:
        value = json.dumps({'version': 1, 'token': token, 'operation': 'flower-r2/read'}).encode()
        connection.sendall(struct.pack('>I', len(value)) + value)
        response = bytearray()
        while part := connection.recv(16384):
            response.extend(part)
        assert struct.unpack('>I', response[:4])[0] == len(response) - 4
        result = json.loads(response[4:])
        assert result['status'] == status
        if status == 'ok':
            assert result['access_key'] == 'dummy-access-key'
            assert result['secret_key'] == 'dummy-secret-key'
print('Container transport and session authentication passed with dummy credentials.')
