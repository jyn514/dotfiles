#!/usr/bin/env python3
"""Narrow authenticated streaming proxy for the Codex responses endpoint."""

from __future__ import annotations

import base64
import fcntl
from http import HTTPStatus
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode
import uuid

AUTH = Path("/var/lib/codex-auth/auth.json")
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
MAX_BODY = 32 * 1024 * 1024
UPSTREAM_HOST = "chatgpt.com"
UPSTREAM_PATH = "/backend-api/codex/responses"
TOKEN_HOST = "auth.openai.com"
TOKEN_PATH = "/oauth/token"
FORWARDED_REQUEST_HEADERS = {
    "accept", "content-encoding", "content-type", "openai-beta",
    "session-id", "x-client-request-id",
}
FORWARDED_RESPONSE_HEADERS = {
    "content-encoding", "content-type", "openai-processing-ms", "request-id",
    "retry-after", "retry-after-ms", "x-request-id",
}
REFRESH_LOCK = threading.Lock()
RETRY_DELAYS = (0.25, 1.0)
SESSION_KEY = os.environ["CODEX_SIDECAR_KEY"]


def connection_diagnostic(connection) -> dict[str, object]:
    socket = getattr(connection, "sock", None)
    if socket is None:
        return {}
    details: dict[str, object] = {}
    try:
        details["tls_version"] = socket.version()
    except Exception:
        pass
    try:
        cipher = socket.cipher()
        if cipher:
            details["tls_cipher"] = cipher[0]
    except Exception:
        pass
    return details


def log_failure(request_id: str, phase: str, body_length: int, error: Exception,
                connection=None) -> None:
    event: dict[str, object] = {
        "event": "upstream_failure",
        "request_id": request_id,
        "phase": phase,
        "body_bytes": body_length,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    if connection is not None:
        event.update(connection_diagnostic(connection))
    print(json.dumps(event, separators=(",", ":"), sort_keys=True), file=sys.stderr, flush=True)


def retryable_tls_failure(error: Exception) -> bool:
    return isinstance(error, ssl.SSLError) and "bad record mac" in str(error).lower()


class UpstreamRequestError(Exception):
    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


def request_upstream(body: bytes, headers: dict[str, str], request_id: str):
    for attempt in range(len(RETRY_DELAYS) + 1):
        upstream = HTTPSConnection(UPSTREAM_HOST, timeout=300)
        phase = "tls_connect"
        try:
            upstream.connect()
            phase = "request_upload"
            upstream.request("POST", UPSTREAM_PATH, body, headers)
            phase = "response_headers"
            return upstream, upstream.getresponse()
        except Exception as error:
            log_failure(request_id, phase, len(body), error, upstream)
            upstream.close()
            if not retryable_tls_failure(error) or attempt == len(RETRY_DELAYS):
                raise UpstreamRequestError(error) from error
            time.sleep(RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")


def jwt_payload(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def read_auth() -> dict:
    data = json.loads(AUTH.read_text(encoding="utf-8"))
    tokens = data.get("tokens")
    if not isinstance(tokens, dict) or not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("Codex authentication is missing OAuth tokens")
    return data


def atomic_auth(data: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".auth.", dir=AUTH.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, AUTH)
    finally:
        temporary.unlink(missing_ok=True)


def credentials() -> tuple[str, str]:
    with REFRESH_LOCK, (AUTH.parent / "refresh.lock").open("a+b") as refresh_lock:
        os.chmod(refresh_lock.name, 0o600)
        fcntl.flock(refresh_lock, fcntl.LOCK_EX)
        data = read_auth()
        tokens = data["tokens"]
        access = tokens["access_token"]
        try:
            expires = int(jwt_payload(access)["exp"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            expires = 0
        if expires <= time.time() + 60:
            body = urlencode({
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
            }).encode()
            connection = HTTPSConnection(TOKEN_HOST, timeout=30)
            connection.request("POST", TOKEN_PATH, body, {
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            })
            response = connection.getresponse()
            payload = response.read()
            connection.close()
            if response.status != HTTPStatus.OK:
                raise RuntimeError(f"Codex token refresh failed ({response.status})")
            refreshed = json.loads(payload)
            access = refreshed["access_token"]
            tokens["access_token"] = access
            tokens["refresh_token"] = refreshed["refresh_token"]
            if refreshed.get("id_token"):
                tokens["id_token"] = refreshed["id_token"]
            data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            atomic_auth(data)
        account = tokens.get("account_id")
        if not account:
            account = jwt_payload(access)["https://api.openai.com/auth"]["chatgpt_account_id"]
        return access, account


def upstream_headers(request_headers, access: str, account: str, body_length: int) -> dict[str, str]:
    headers = {
        key: value for key, value in request_headers.items()
        if key.lower() in FORWARDED_REQUEST_HEADERS
    }
    headers.update({
        "Authorization": f"Bearer {access}",
        "chatgpt-account-id": account,
        "originator": "pi",
        "User-Agent": "codex-sandbox-sidecar",
        "Content-Length": str(body_length),
        "Host": UPSTREAM_HOST,
    })
    return headers


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "codex-auth-proxy"

    def log_message(self, format: str, *args: object) -> None:
        # Do not log request paths, headers, prompts, or response bodies.
        return

    def error(self, status: HTTPStatus, message: str) -> None:
        body = (message + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self.error(HTTPStatus.NOT_FOUND, "not found")
            return
        body = b"ok\n"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/codex/responses":
            self.error(HTTPStatus.NOT_FOUND, "not found")
            return
        if self.headers.get("Authorization") != f"Bearer {SESSION_KEY}":
            self.error(HTTPStatus.UNAUTHORIZED, "unauthorized")
            return
        if self.headers.get("Transfer-Encoding"):
            self.error(HTTPStatus.BAD_REQUEST, "chunked request bodies are not accepted")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid request size")
            return
        body = self.rfile.read(length)
        request_id = uuid.uuid4().hex
        try:
            access, account = credentials()
            headers = upstream_headers(self.headers, access, account, len(body))
        except Exception as error:
            log_failure(request_id, "credentials", len(body), error)
            self.error(HTTPStatus.BAD_GATEWAY, f"Codex sidecar authentication or connection failed: {error}")
            return
        try:
            upstream, response = request_upstream(body, headers, request_id)
        except UpstreamRequestError as failure:
            self.error(
                HTTPStatus.BAD_GATEWAY,
                f"Codex sidecar authentication or connection failed: {failure.error}",
            )
            return
        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() in FORWARDED_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            while chunk := response.read(64 * 1024):
                self.wfile.write(f"{len(chunk):x}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            log_failure(request_id, "response_stream", len(body), error, upstream)
        finally:
            upstream.close()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8787), Handler)
    server.serve_forever()
