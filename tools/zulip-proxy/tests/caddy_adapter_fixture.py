#!/usr/bin/env python3
"""Disposable application or native typed adapter client; stdlib only."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
import socket
import sys


def application():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def do_GET(self):
            if self.path == "/reset":
                requests.clear()
                body = b"{}"
            elif self.path == "/state":
                body = json.dumps(requests).encode()
            else:
                requests.append({"path": self.path, "authorization": self.headers.get("Authorization"),
                    "body_length": self.headers.get("Content-Length", "0")})
                body = json.dumps({"result": "success", "messages": [], "found_newest": True,
                    "topics": [], "streams": []}).encode()
            self.send_response_only(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    HTTPServer(("0.0.0.0", 8082), Handler).serve_forever()


def adapter_client():
    sys.path.insert(0, "/adapter")
    spec = importlib.util.spec_from_file_location("zulip_adapter", "/adapter/server.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    framed = sys.stdin.buffer.read()
    client, server = socket.socketpair()
    try:
        client.sendall(framed)
        client.shutdown(socket.SHUT_WR)
        adapter.serve_connection(server, adapter.caddy_endpoint(adapter.CADDY_ENDPOINT), adapter.SESSION_KEY)
        stream = client.makefile("rb")
        try:
            header = adapter.read_exact(stream, 4)
            body = adapter.read_exact(stream, int.from_bytes(header, "big"))
            sys.stdout.buffer.write(header + body)
        finally:
            stream.close()
    finally:
        client.close(); server.close()


if __name__ == "__main__":
    {"application": application, "adapter": adapter_client}[sys.argv[1]]()
