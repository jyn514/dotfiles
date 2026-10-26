"""Metadata reads stay on the selected socket and retain lookup failures."""

from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lima.docker_api import hijack, inspect, request, stream


class DockerApiTest(unittest.TestCase):
    def test_selected_socket_returns_metadata_and_missing_image_diagnostic(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                status, value = ((200, {'ID': 'owned'}) if self.path == '/info' else
                                 (404, {'message': 'No such image: missing'}))
                data = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'engine.sock')
            with socketserver.UnixStreamServer(path, Handler) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    with patch.dict('os.environ', DOCKER_HOST='tcp://wrong:2375', HTTP_PROXY='http://wrong:8080'):
                        self.assertEqual({'ID': 'owned'}, inspect(path, '/info', ['docker', 'info']))
                        command = ['docker', 'image', 'inspect', 'missing']
                        with self.assertRaises(subprocess.CalledProcessError) as failure:
                            inspect(path, '/images/missing/json', command)
                    self.assertEqual(failure.exception.cmd, command)
                    self.assertEqual(failure.exception.stderr, 'No such image: missing')
                    self.assertEqual(failure.exception.status, 404)
                    self.assertEqual(requests, ['/info', '/images/missing/json'])
                finally:
                    server.shutdown()
                    thread.join()

    def test_mutation_uses_json_on_selected_socket_and_accepts_created_status(self):
        observed = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                observed['path'] = self.path
                observed['type'] = self.headers.get('Content-Type')
                observed['payload'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                data = json.dumps({'Id': 'created'}).encode()
                self.send_response(201)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'engine.sock')
            with socketserver.UnixStreamServer(path, Handler) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    result = request(path, 'POST', '/networks/create', ['docker', 'network', 'create'],
                                     payload={'Name': 'owned'}, expected=(201,))
                finally:
                    server.shutdown()
                    thread.join()
        self.assertEqual({'Id': 'created'}, result)
        self.assertEqual({'path': '/networks/create', 'type': 'application/json',
                          'payload': {'Name': 'owned'}}, observed)

    def test_hijack_retains_bytes_after_upgrade_headers(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                observed.append(self.path)
                self.send_response(101)
                self.send_header('Connection', 'Upgrade')
                self.send_header('Upgrade', 'tcp')
                self.end_headers()
                self.wfile.write(b'raw\rterminal')
                self.wfile.flush()

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'engine.sock')
            with socketserver.UnixStreamServer(path, Handler) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    transport, response = hijack(
                        path, '/containers/owned/attach', ['docker', 'start', '--attach', 'owned'],
                        query={'stream': '1', 'stdin': '0'},
                    )
                    self.assertEqual(b'raw\rterminal', response.read())
                    response.close()
                    transport.close()
                finally:
                    server.shutdown()
                    thread.join()
        self.assertEqual(['/containers/owned/attach?stream=1&stdin=0'], observed)

    def test_stream_retains_response_body_for_incremental_reads(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', '5')
                self.end_headers()
                self.wfile.write(b'ready')

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'engine.sock')
            with socketserver.UnixStreamServer(path, Handler) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    connection, response = stream(
                        path, 'GET', '/containers/owned/logs', ['docker', 'logs', 'owned'])
                    self.assertEqual(b'ready', response.read())
                    response.close()
                    connection.close()
                finally:
                    server.shutdown()
                    thread.join()


if __name__ == '__main__':
    unittest.main()
