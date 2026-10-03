"""Local HTTP oracle regressions; no Docker, VM, or external network needed."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest

from docker_network_probe import assert_http_200


@contextmanager
def endpoint(kind):
    accepted = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            accepted.set()
            if kind == 'tcp-only':
                release.wait(2)
                return
            self.send_response(503 if kind == 'unavailable' else 200)
            self.send_header('Content-Length', '5')
            self.end_headers()
            if kind == 'headers-only':
                release.wait(2)
            else:
                self.wfile.write(b'ready')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
    worker.start()
    try:
        yield f'127.0.0.1:{server.server_port}', accepted
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class HTTPProbeTest(unittest.TestCase):
    def test_complete_http_200(self):
        with endpoint('ready') as (target, accepted):
            assert_http_200(target, timeout=1)
            self.assertTrue(accepted.is_set())

    def test_accepting_tcp_proxy_without_response_is_not_success(self):
        with endpoint('tcp-only') as (target, accepted):
            # The old oracle succeeds against exactly this stalled endpoint.
            with socket.create_connection(('127.0.0.1', int(target.rsplit(':', 1)[1])), timeout=1):
                pass
            with self.assertRaisesRegex(AssertionError, 'no completed HTTP 200'):
                assert_http_200(target, timeout=0.2)
            self.assertTrue(accepted.is_set(), 'HTTP reached the accepting proxy')

    def test_200_headers_without_completed_body_are_not_success(self):
        with endpoint('headers-only') as (target, accepted):
            with self.assertRaisesRegex(AssertionError, 'no completed HTTP 200'):
                assert_http_200(target, timeout=0.2)
            self.assertTrue(accepted.is_set())

    def test_non_200_is_not_success(self):
        with endpoint('unavailable') as (target, _):
            with self.assertRaisesRegex(AssertionError, 'no completed HTTP 200'):
                assert_http_200(target, timeout=0.2)

    def test_direct_script_http_mode(self):
        with endpoint('ready') as (target, _):
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('docker_network_probe.py')),
                                     'http', target], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS: http ' + target, result.stdout)


if __name__ == '__main__':
    unittest.main()
