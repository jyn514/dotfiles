"""Credential-free fixed-target relay for the disposable Lima network gate."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
from urllib.request import ProxyHandler, build_opener


class Relay(BaseHTTPRequestHandler):
    def do_GET(self):
        with build_opener(ProxyHandler({})).open(sys.argv[1], timeout=5) as response:
            body = response.read()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", 18081), Relay).serve_forever()
