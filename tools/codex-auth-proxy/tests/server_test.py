from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
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
