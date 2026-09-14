from __future__ import annotations

import base64
from contextlib import contextmanager
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest import mock


SERVER = Path(__file__).resolve().parents[1] / "server.py"
os.environ.setdefault("CODEX_SIDECAR_KEY", "session-key")
spec = importlib.util.spec_from_file_location("codex_auth_proxy", SERVER)
assert spec and spec.loader
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


def token(expires: int, account: str = "account") -> str:
    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': expires, 'https://api.openai.com/auth': {'chatgpt_account_id': account}})}.signature"


class FakeResponse:
    status = 200

    def read(self) -> bytes:
        return json.dumps({
            "access_token": token(4_000_000_000, "refreshed-account"),
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }).encode()


class FakeConnection:
    request_args = None

    def __init__(self, host: str, timeout: int) -> None:
        self.host = host; self.timeout = timeout

    sock = None

    def connect(self) -> None:
        pass

    def request(self, *args) -> None:
        type(self).request_args = args

    def getresponse(self) -> FakeResponse:
        return FakeResponse()

    def close(self) -> None:
        pass


class FakeSocket:
    def version(self) -> str:
        return "TLSv1.3"

    def cipher(self) -> tuple[str, str, int]:
        return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)


class DiagnosticTest(unittest.TestCase):
    def test_logs_failure_metadata_without_request_content(self) -> None:
        connection = mock.Mock(sock=FakeSocket())
        error = ssl.SSLError("bad record mac")
        with mock.patch.object(proxy.sys, "stderr") as stderr:
            proxy.log_failure("local-id", "request_upload", 123456, error, connection)

        event = json.loads(stderr.write.call_args_list[0].args[0])
        self.assertEqual({
            "event": "upstream_failure",
            "request_id": "local-id",
            "phase": "request_upload",
            "body_bytes": 123456,
            "error_type": "SSLError",
            "tls_version": "TLSv1.3",
            "tls_cipher": "TLS_AES_256_GCM_SHA384",
        }, event)

    def test_tolerates_connection_without_tls_socket(self) -> None:
        self.assertEqual({}, proxy.connection_diagnostic(mock.Mock(sock=None)))


class StreamingAndRetryTest(unittest.TestCase):
    def test_nonempty_slow_request_stream_obeys_total_deadline(self) -> None:
        class Slow:
            def read(self, size): time.sleep(.03); return b'x'
        connection=mock.Mock(sock=mock.Mock(),timeout=1)
        with self.assertRaises(TimeoutError):
            proxy.broker.stream_request(connection,'POST','/fixed',{},Slow(),1,1,time.monotonic()+.01,mock.Mock())
        connection.send.assert_not_called()

    def test_request_is_streamed_in_bounded_chunks(self) -> None:
        connection = mock.Mock()
        body = b'x' * (proxy.broker.CHUNK + 3)
        proxy.broker.stream_request(connection, 'POST', '/fixed', {}, io.BytesIO(body), len(body), len(body))
        self.assertEqual([proxy.broker.CHUNK, 3], [len(call.args[0]) for call in connection.send.call_args_list])

    def test_premature_request_eof_after_streaming_is_terminal(self) -> None:
        connection = mock.Mock()
        with self.assertRaises(EOFError):
            proxy.broker.stream_request(connection, 'POST', '/fixed', {}, io.BytesIO(b'partial'), 99, 100)
        connection.send.assert_called_once_with(b'partial')

    def test_no_retry_after_uncertain_transmission(self) -> None:
        connection = mock.Mock(); connection.send.side_effect = OSError('outcome unknown')
        with self.assertRaises(OSError):
            proxy.broker.stream_request(connection, 'POST', '/fixed', {}, io.BytesIO(b'body'), 4, 4)
        connection.send.assert_called_once()


class BrokerPolicyTest(unittest.TestCase):
    def test_malformed_targets_encoded_traversal_and_query_are_rejected(self) -> None:
        rejected = ['https://evil/codex/responses', '//evil/x', '/codex/%2fresponses',
                    '/codex/../responses', '/codex/responses?secret=1', '/codex/%GG']
        for target in rejected:
            with self.subTest(target=target), self.assertRaises(proxy.broker.PolicyError):
                proxy.broker.parse_target(target, proxy.ROUTE)

    def test_fixed_route_constructs_only_fixed_upstream_target(self) -> None:
        self.assertEqual((proxy.UPSTREAM_PATH, ''), proxy.broker.parse_target('/codex/responses', proxy.ROUTE))

    def test_forbidden_and_unknown_headers_do_not_cross_boundary(self) -> None:
        clean = proxy.broker.filter_request_headers({'Host':'evil', 'Authorization':'Bearer session',
            'X-Forwarded-For':'127.0.0.1', 'Content-Type':'application/json'}, proxy.ROUTE)
        self.assertEqual({'Content-Type':'application/json'}, clean)
        with self.assertRaises(proxy.broker.PolicyError):
            proxy.broker.filter_request_headers({'Cookie':'secret'}, proxy.ROUTE)

    def test_header_and_body_limits(self) -> None:
        tiny = proxy.broker.Route('x','example.com','/x','/x',frozenset({'POST'}),frozenset({'x'}),frozenset(),max_headers=4)
        with self.assertRaises(proxy.broker.LimitError): proxy.broker.filter_request_headers({'X':'long'}, tiny)
        with self.assertRaises(proxy.broker.LimitError):
            proxy.broker.stream_request(mock.Mock(),'POST','/x',{},io.BytesIO(b'123'),3,2)

    def test_dns_private_and_mixed_answers_fail_closed(self) -> None:
        answers=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))]
        with mock.patch.object(proxy.broker.socket,'getaddrinfo',return_value=answers):
            with self.assertRaises(proxy.broker.PolicyError): proxy.broker.public_addresses('example.com')

    def test_open_upstream_pins_the_policy_checked_dns_answers(self) -> None:
        answers=[(2,1,6,'',('93.184.216.34',443))]
        with mock.patch.object(proxy.broker,'public_addresses',return_value=answers) as resolve:
            connection=proxy.broker.open_upstream(proxy.ROUTE)
        resolve.assert_called_once_with(proxy.UPSTREAM_HOST)
        self.assertIs(connection._answers,answers)

    def test_response_transfer_status_and_singleton_duplicates(self) -> None:
        bad=[(200,[('Transfer-Encoding','gzip')]),(101,[]),(204,[('Content-Length','1')]),
             (205,[('Transfer-Encoding','chunked')]),
             (200,[('X-Request-Id','a'),('x-request-id','b')]),
             (200,[('Content-Type','text/plain\r\nInjected: yes')])]
        for status,headers in bad:
            with self.subTest(status=status,headers=headers),self.assertRaises(proxy.broker.PolicyError):
                proxy.broker.response_framing(status,headers,proxy.ROUTE)
        self.assertEqual((0,True),proxy.broker.response_framing(204,[('Content-Length','0')],proxy.ROUTE))
        self.assertEqual((0,True),proxy.broker.response_framing(205,[('Content-Length','0')],proxy.ROUTE))

    def test_cancel_upstream_shuts_down_before_close(self) -> None:
        connection = mock.Mock()
        proxy.cancel_upstream(connection)
        connection.sock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        connection.close.assert_called_once_with()

    def test_empty_session_key_is_rejected_at_startup(self) -> None:
        environment=dict(os.environ,CODEX_SIDECAR_KEY='')
        result=subprocess.run([sys.executable,str(SERVER)],env=environment,capture_output=True,text=True)
        self.assertNotEqual(0,result.returncode)
        self.assertNotIn('CODEX_SIDECAR_KEY=',result.stderr)


@contextmanager
def running_handler():
    server = proxy.ThreadingHTTPServer(('127.0.0.1', 0), proxy.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield server.server_address
    finally: server.shutdown(); server.server_close(); thread.join()


def raw_request(address, wire):
    connection = socket.create_connection(address, timeout=2)
    connection.sendall(wire); connection.shutdown(socket.SHUT_WR)
    chunks=[]
    while True:
        data=connection.recv(65536)
        if not data: break
        chunks.append(data)
    connection.close(); return b''.join(chunks)


class RealHTTPHandlerTest(unittest.TestCase):
    def test_wrong_token_and_exact_method_route_fail_closed(self):
        cases = [
            b'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer wrong\r\nContent-Length: 0\r\n\r\n',
            b'PUT /codex/responses HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n',
            f'POST /codex/responses? HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\nContent-Length: 0\r\n\r\n'.encode()]
        with running_handler() as address:
            responses=[raw_request(address,case) for case in cases]
        self.assertIn(b' 401 ',responses[0]); self.assertIn(b' 405 ',responses[1]); self.assertIn(b' 400 ',responses[2])

    def test_head_health_preserves_health_contract_without_a_body(self):
        with running_handler() as address:
            response=raw_request(address,b'HEAD /health HTTP/1.1\r\nHost: x\r\n\r\n')
        self.assertIn(b' 200 ',response); self.assertIn(b'Content-Length: 3',response)
        self.assertTrue(response.endswith(b'\r\n\r\n'))

    def test_folded_forwarded_header_is_rejected(self):
        wire=(f'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\n'
              'Content-Length: 0\r\nContent-Type: text/plain\r\n injected: yes\r\n\r\n').encode()
        with running_handler() as address: response=raw_request(address,wire)
        self.assertIn(b' 400 ',response)

    def test_duplicate_critical_and_ambiguous_framing_are_rejected(self):
        wire=(f'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\n'
              f'Authorization: Bearer {proxy.SESSION_KEY}\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n').encode()
        with running_handler() as address: response=raw_request(address,wire)
        self.assertIn(b' 400 ',response); self.assertNotIn(b'credential',response.lower())

    def test_redirect_is_rejected_before_downstream_headers(self):
        response=mock.Mock(status=302,reason='Found'); response.getheaders.return_value=[('Location','https://evil/')]
        upstream=mock.Mock(sock=mock.Mock()); response.read.return_value=b''
        with mock.patch.object(proxy,'credentials',return_value=('access','account')), \
             mock.patch.object(proxy,'request_upstream',return_value=(upstream,response)), running_handler() as address:
            wire=f'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\nContent-Length: 0\r\n\r\n'.encode()
            actual=raw_request(address,wire)
        self.assertIn(b' 502 ',actual); self.assertNotIn(b'Location:',actual)

    def test_premature_content_length_eof_has_no_terminating_chunk(self):
        response=mock.Mock(status=200,reason='OK'); response.getheaders.return_value=[('Content-Length','9')]
        response.read.side_effect=[b'part',b'']; upstream=mock.Mock(sock=mock.Mock())
        with mock.patch.object(proxy,'credentials',return_value=('access','account')), \
             mock.patch.object(proxy,'request_upstream',return_value=(upstream,response)), running_handler() as address:
            wire=f'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\nContent-Length: 0\r\n\r\n'.encode()
            actual=raw_request(address,wire)
        self.assertIn(b'4\r\npart\r\n',actual); self.assertFalse(actual.endswith(b'0\r\n\r\n'))

    def test_declared_response_limit_is_rejected_before_success_headers(self):
        response=mock.Mock(status=200,reason='OK'); response.getheaders.return_value=[('Content-Length',str(proxy.ROUTE.max_response_body+1))]
        upstream=mock.Mock(sock=mock.Mock())
        with mock.patch.object(proxy,'credentials',return_value=('access','account')), \
             mock.patch.object(proxy,'request_upstream',return_value=(upstream,response)), running_handler() as address:
            wire=f'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\nContent-Length: 0\r\n\r\n'.encode()
            actual=raw_request(address,wire)
        self.assertIn(b' 502 ',actual); self.assertNotIn(b' 200 ',actual)

    def test_downstream_disconnect_closes_upstream_while_waiting(self):
        closed=threading.Event(); upstream=mock.Mock(); upstream.close.side_effect=lambda: closed.set()
        def waiting(source,headers,request_id,length,deadline,uploaded,downstream_socket):
            uploaded(upstream)
            closed.wait(2)
            raise proxy.UpstreamRequestError(ConnectionError('cancelled'))
        with mock.patch.object(proxy,'credentials',return_value=('access','account')), \
             mock.patch.object(proxy,'request_upstream',side_effect=waiting), running_handler() as address:
            client=socket.create_connection(address,timeout=2)
            client.sendall(f'POST /codex/responses HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {proxy.SESSION_KEY}\r\nContent-Length: 0\r\n\r\n'.encode())
            client.close()
            self.assertTrue(closed.wait(1))

    def test_client_errors_never_echo_supplied_secrets(self):
        secret=b'please-do-not-log-this'
        wire=b'POST http://evil/'+secret+b' HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer '+secret+b'\r\nContent-Length: 0\r\n\r\n'
        with running_handler() as address: response=raw_request(address,wire)
        self.assertNotIn(secret,response)


class HeaderPolicyTest(unittest.TestCase):
    def test_replaces_authority_and_drops_forwarding_headers(self) -> None:
        headers = proxy.upstream_headers({
            "Authorization": "Bearer attacker",
            "Host": "attacker.invalid",
            "X-Forwarded-Host": "attacker.invalid",
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
        }, "real-access", "account", 42)

        self.assertEqual("Bearer real-access", headers["Authorization"])
        self.assertEqual(proxy.UPSTREAM_HOST, headers["Host"])
        self.assertEqual("account", headers["chatgpt-account-id"])
        self.assertEqual("42", headers["Content-Length"])
        self.assertNotIn("X-Forwarded-Host", headers)


class CredentialTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.auth = directory / "auth.json"
        self.auth.write_text(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": token(1),
                "refresh_token": "old-refresh",
                "account_id": "old-account",
            },
        }), encoding="utf-8")
        self.auth.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_refreshes_and_replaces_auth_transactionally(self) -> None:
        FakeConnection.request_args = None
        with mock.patch.object(proxy, "AUTH", self.auth), mock.patch.object(proxy.profile.broker, "open_upstream", side_effect=lambda route: FakeConnection(route.host, route.timeout)):
            access, account = proxy.credentials()

        self.assertEqual("old-account", account)
        self.assertEqual("refreshed-account", proxy.jwt_payload(access)["https://api.openai.com/auth"]["chatgpt_account_id"])
        saved = json.loads(self.auth.read_text(encoding="utf-8"))
        self.assertEqual("new-refresh", saved["tokens"]["refresh_token"])
        self.assertEqual(0o600, self.auth.stat().st_mode & 0o777)
        self.assertIn(b"refresh_token=old-refresh", FakeConnection.request_args[2])

    def test_refresh_total_deadline_does_not_modify_credentials(self) -> None:
        before=self.auth.read_bytes(); connection=mock.Mock(sock=None)
        with mock.patch.object(proxy,'AUTH',self.auth), \
             mock.patch.object(proxy.profile.broker,'open_upstream',return_value=connection), \
             mock.patch.object(proxy.profile.time,'monotonic',side_effect=[0,31]):
            with self.assertRaises(TimeoutError): proxy.credentials()
        self.assertEqual(before,self.auth.read_bytes())

    def test_refresh_failure_does_not_modify_credentials(self) -> None:
        before = self.auth.read_bytes()
        response = mock.Mock(status=500); response.read.side_effect = [b'failure', b'']
        connection = mock.Mock(timeout=30); connection.getresponse.return_value = response
        with mock.patch.object(proxy, 'AUTH', self.auth), mock.patch.object(proxy.profile.broker, 'open_upstream', return_value=connection):
            with self.assertRaises(RuntimeError): proxy.credentials()
        self.assertEqual(before, self.auth.read_bytes())

    def test_valid_access_token_does_not_refresh(self) -> None:
        data = json.loads(self.auth.read_text(encoding="utf-8"))
        data["tokens"]["access_token"] = token(4_000_000_000)
        self.auth.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(proxy, "AUTH", self.auth), mock.patch.object(proxy, "HTTPSConnection") as connection:
            access, account = proxy.credentials()
        self.assertEqual("old-account", account)
        self.assertEqual(4_000_000_000, proxy.jwt_payload(access)["exp"])
        connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
