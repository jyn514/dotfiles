"""Exercise the host editor protocol from an actual agent container."""

import json
import os
import socket
import struct


def receive(stream):
    length, = struct.unpack(">I", stream.read(4))
    return json.loads(stream.read(length))


address, port = os.environ["CODEX_SANDBOX_EDITOR_ADDRESS"].rsplit(":", 1)
for token, accepted in (("wrong-token", False), (os.environ["CODEX_SANDBOX_EDITOR_TOKEN"], True)):
    with socket.create_connection((address, int(port)), timeout=10) as connection:
        request = json.dumps({"version": 1, "token": token, "content": "before"}).encode()
        connection.sendall(struct.pack(">I", len(request)) + request)
        with connection.makefile("rb") as stream:
            first = receive(stream)
            if accepted:
                assert first == {"version": 1, "status": "editing"}, first
                assert receive(stream) == {"version": 1, "status": "complete", "content": "before edited"}
            else:
                assert first["status"] == "failed", first
print("Host editor relay authenticated and returned edited content.")
