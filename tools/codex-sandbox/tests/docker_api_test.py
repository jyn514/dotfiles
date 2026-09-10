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
from lima.docker_api import inspect


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
                    self.assertEqual(requests, ['/info', '/images/missing/json'])
                finally:
                    server.shutdown()
                    thread.join()


if __name__ == '__main__':
    unittest.main()
