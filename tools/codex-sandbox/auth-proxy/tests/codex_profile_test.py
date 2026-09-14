from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs

PATH = Path(__file__).resolve().parents[1] / "codex_profile.py"
SPEC = importlib.util.spec_from_file_location("codex_profile_tested", PATH)
assert SPEC and SPEC.loader
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)
HELPER_SPEC = importlib.util.spec_from_file_location("profile_helper_tested", PATH.with_name("profile_helper.py"))
assert HELPER_SPEC and HELPER_SPEC.loader
helper = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(helper)


def token(exp: float, account: str | None = "account") -> str:
    claims = {"exp": exp}
    if account is not None:
        claims["https://api.openai.com/auth"] = {"chatgpt_account_id": account}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


class Response:
    def __init__(self, body: bytes, status: int = 200, length: str | None = None):
        self.body, self.status = body, status
        self._length = str(len(body)) if length is None else length
    def getheader(self, name):
        return self._length if name == "Content-Length" else None
    def read(self, size=-1):
        result, self.body = self.body[:size], self.body[size:]
        return result


class Connection:
    instances = []
    response = Response(b"{}")
    failure = None
    def __init__(self, timeout, deadline):
        self.timeout, self.deadline, self.sock = timeout, deadline, None
        self.calls = []
        type(self).instances.append(self)
        if type(self).failure:
            raise type(self).failure
    def request(self, *args): self.calls.append(args)
    def getresponse(self): return type(self).response
    def close(self): self.closed = True


class CodexProfileTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.auth = Path(self.temporary.name) / "auth.json"
        self.original = {"tokens": {
            "access_token": token(0), "refresh_token": "old-refresh", "account_id": "account",
        }}
        self.auth.write_text(json.dumps(self.original), encoding="utf-8")
        os.chmod(self.auth, 0o600)
        self.auth_patch = mock.patch.object(profile, "AUTH", self.auth)
        self.auth_patch.start()
        Connection.instances = []; Connection.failure = None
    def tearDown(self):
        self.auth_patch.stop(); self.temporary.cleanup()

    def refreshed(self, *, account="account", **updates):
        value = {"access_token": token(time.time() + 3600, account), "refresh_token": "new-refresh"}
        value.update(updates)
        return json.dumps(value).encode()

    def assert_original(self):
        self.assertEqual(self.original, json.loads(self.auth.read_text()))

    def test_valid_token_never_uses_network(self):
        data = {"tokens": {**self.original["tokens"], "access_token": token(time.time() + 3600)}}
        self.auth.write_text(json.dumps(data))
        with mock.patch.object(profile, "_post_token") as post:
            self.assertEqual((data["tokens"]["access_token"], "account"), profile.credentials())
        post.assert_not_called()

    def test_refresh_uses_only_fixed_oauth_request(self):
        response_body = self.refreshed()
        Connection.response = Response(response_body)
        with mock.patch.object(profile, "_PinnedHTTPSConnection", Connection):
            profile.credentials()
        method, path, sent, headers = Connection.instances[0].calls[0]
        self.assertEqual(("POST", "/oauth/token"), (method, path))
        self.assertEqual({"grant_type": ["refresh_token"], "refresh_token": ["old-refresh"], "client_id": [profile.CLIENT_ID]}, parse_qs(sent.decode()))
        self.assertEqual({"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(sent))}, headers)

    def test_success_replaces_complete_state_transactionally_with_0600_mode(self):
        with mock.patch.object(profile, "_post_token", return_value=(200, self.refreshed(id_token="new-id"))):
            access, account = profile.credentials()
        saved = json.loads(self.auth.read_text())
        self.assertEqual((access, account), (saved["tokens"]["access_token"], "account"))
        self.assertEqual(("new-refresh", "new-id"), (saved["tokens"]["refresh_token"], saved["tokens"]["id_token"]))
        self.assertEqual(0o600, self.auth.stat().st_mode & 0o777)

    def test_dns_connect_http_decode_schema_and_deadline_failures_preserve_state(self):
        failures = [
            OSError("dns"), OSError("connect"),
            (500, self.refreshed()), (200, b"{"), (200, b"{}"), TimeoutError("deadline"),
        ]
        for failure in failures:
            self.auth.write_text(json.dumps(self.original))
            effect = failure if isinstance(failure, tuple) else failure
            with self.subTest(failure=repr(failure)), mock.patch.object(profile, "_post_token", side_effect=effect if isinstance(effect, BaseException) else None, return_value=effect if isinstance(effect, tuple) else mock.DEFAULT):
                with self.assertRaises(Exception): profile.credentials(deadline=time.monotonic() + 1)
            self.assert_original()

    def test_oversized_response_is_rejected(self):
        Connection.response = Response(b"", length=str(profile.MAX_TOKEN_RESPONSE + 1))
        with mock.patch.object(profile, "_PinnedHTTPSConnection", Connection):
            with self.assertRaisesRegex(RuntimeError, "too large"):
                profile._post_token(b"x", time.monotonic() + 5)
        self.assert_original()

    def test_refresh_cannot_change_account_identity(self):
        with mock.patch.object(profile, "_post_token", return_value=(200, self.refreshed(account="other"))):
            with self.assertRaisesRegex(RuntimeError, "identity"):
                profile.credentials()
        self.assert_original()

    def test_account_is_derived_when_legacy_state_has_no_account_id(self):
        del self.original["tokens"]["account_id"]
        self.auth.write_text(json.dumps(self.original))
        with mock.patch.object(profile, "_post_token", return_value=(200, self.refreshed(account="derived"))):
            _, account = profile.credentials()
        self.assertEqual("derived", account)

    def test_dns_result_must_be_public_and_well_formed(self):
        parent = mock.Mock()
        process = mock.Mock(); process.is_alive.return_value = False
        for result in [("ok", [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]), ("ok", [(1,)]), ("surprise", [])]:
            parent.poll.return_value = True; parent.recv.return_value = result
            with self.subTest(result=result), mock.patch.object(profile.multiprocessing, "Pipe", return_value=(parent, mock.Mock())), mock.patch.object(profile.multiprocessing, "Process", return_value=process):
                with self.assertRaises((RuntimeError, OSError)):
                    profile._public_addresses(time.monotonic() + 1)

    def test_dns_timeout_kills_and_reaps_child(self):
        parent, writer, process = mock.Mock(), mock.Mock(), mock.Mock()
        parent.poll.return_value = False; process.is_alive.return_value = True
        with mock.patch.object(profile.multiprocessing, "Pipe", return_value=(parent, writer)), mock.patch.object(profile.multiprocessing, "Process", return_value=process):
            with self.assertRaises(TimeoutError): profile._public_addresses(time.monotonic() + 1)
        process.kill.assert_called_once(); process.join.assert_called_once()

    def test_helper_sigalrm_bounds_blocked_dns_child(self):
        def blocked(_writer):
            time.sleep(10)
        started = time.monotonic()
        with mock.patch.object(profile, "_resolve_in_child", blocked):
            with self.assertRaisesRegex(TimeoutError, "operation deadline"):
                with helper.operation_deadline(.05) as deadline:
                    profile._public_addresses(deadline + 10)
        self.assertLess(time.monotonic() - started, 1)


if __name__ == "__main__": unittest.main()
