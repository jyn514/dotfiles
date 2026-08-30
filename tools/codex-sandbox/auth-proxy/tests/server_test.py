from __future__ import annotations

import base64
import importlib.util
import json
import os
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
        self.host = host

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
            "error": "('bad record mac',)",
            "tls_version": "TLSv1.3",
            "tls_cipher": "TLS_AES_256_GCM_SHA384",
        }, event)

    def test_tolerates_connection_without_tls_socket(self) -> None:
        self.assertEqual({}, proxy.connection_diagnostic(mock.Mock(sock=None)))


class UpstreamRetryTest(unittest.TestCase):
    def test_retries_bad_record_mac_with_a_fresh_connection(self) -> None:
        failure = ssl.SSLError("ssl/tls alert bad record mac")
        first = mock.Mock()
        first.request.side_effect = failure
        second = mock.Mock()
        response = mock.sentinel.response
        second.getresponse.return_value = response

        with mock.patch.object(proxy, "HTTPSConnection", side_effect=[first, second]), \
                mock.patch.object(proxy, "log_failure") as log_failure, \
                mock.patch.object(proxy.time, "sleep") as sleep:
            connection, actual_response = proxy.request_upstream(
                b"request", {"Content-Type": "application/json"}, "local-id",
            )

        self.assertIs(second, connection)
        self.assertIs(response, actual_response)
        first.close.assert_called_once_with()
        sleep.assert_called_once_with(proxy.RETRY_DELAYS[0])
        log_failure.assert_called_once_with(
            "local-id", "request_upload", 7, failure, first,
        )

    def test_does_not_retry_unrelated_tls_failure(self) -> None:
        failure = ssl.SSLError("certificate verify failed")
        connection = mock.Mock()
        connection.connect.side_effect = failure

        with mock.patch.object(proxy, "HTTPSConnection", return_value=connection), \
                mock.patch.object(proxy, "log_failure"), \
                mock.patch.object(proxy.time, "sleep") as sleep:
            with self.assertRaises(proxy.UpstreamRequestError) as raised:
                proxy.request_upstream(b"request", {}, "local-id")

        self.assertIs(failure, raised.exception.error)
        connection.close.assert_called_once_with()
        sleep.assert_not_called()


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
        with mock.patch.object(proxy, "AUTH", self.auth), mock.patch.object(proxy, "HTTPSConnection", FakeConnection):
            access, account = proxy.credentials()

        self.assertEqual("old-account", account)
        self.assertEqual("refreshed-account", proxy.jwt_payload(access)["https://api.openai.com/auth"]["chatgpt_account_id"])
        saved = json.loads(self.auth.read_text(encoding="utf-8"))
        self.assertEqual("new-refresh", saved["tokens"]["refresh_token"])
        self.assertEqual(0o600, self.auth.stat().st_mode & 0o777)
        self.assertIn(b"refresh_token=old-refresh", FakeConnection.request_args[2])

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
