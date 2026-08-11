#!/usr/bin/env python3
"""Exercise the real Zulip proxy image, socket, TLS, and client together."""

from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[3]
IMAGE_BUILDER = ROOT / ".agents" / "sandbox" / "zulip-proxy-image"
CLIENT = ROOT / "tools" / "zulip-proxy" / "client"


def run(arguments: list[str], **options) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(arguments, check=True, **options)
    except subprocess.CalledProcessError as error:
        stderr = error.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        detail = stderr.strip() if isinstance(stderr, str) else ""
        raise RuntimeError(detail or f"command failed: {arguments[0]}") from error


class ZulipHandler(BaseHTTPRequestHandler):
    request_error: str | None = None

    def do_GET(self) -> None:
        try:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            expected_auth = "Basic " + base64.b64encode(
                b"reader@example.test:test-key"
            ).decode("ascii")
            assert self.headers["Authorization"] == expected_auth
            if parsed.path == "/api/v1/messages":
                assert json.loads(query["narrow"][0]) == [
                    {"operator": "channel", "operand": 456},
                    {"operator": "topic", "operand": "private/topic"},
                    {"operator": "sent-after", "operand": "2026-03-01"},
                    {"operator": "sent-before", "operand": "2026-04-01"},
                ]
                response = {
                    "result": "success",
                    "messages": [{"id": 789, "content": "container integration"}],
                    "found_newest": True,
                }
            else:
                assert parsed.path == "/api/v1/users/me/456/topics"
                assert not query
                response = {
                    "result": "success",
                    "topics": [{"name": "private/topic", "max_id": 789}],
                }
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (AssertionError, KeyError, ValueError) as error:
            type(self).request_error = str(error) or "upstream request assertion failed"
            self.send_error(400)

    def log_message(self, format: str, *arguments: object) -> None:
        pass


def generate_certificate(directory: Path) -> tuple[Path, Path]:
    config = directory / "openssl.cnf"
    config.write_text(
        "[req]\n"
        "distinguished_name=dn\n"
        "x509_extensions=ext\n"
        "prompt=no\n"
        "[dn]\n"
        "CN=host.docker.internal\n"
        "[ext]\n"
        "subjectAltName=DNS:host.docker.internal\n"
        "basicConstraints=critical,CA:TRUE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n",
        encoding="utf-8",
    )
    certificate = directory / "certificate.pem"
    key = directory / "key.pem"
    run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-days", "1", "-config", str(config), "-keyout", str(key),
        "-out", str(certificate),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return certificate, key


def main() -> None:
    if shutil.which("docker") is None or shutil.which("openssl") is None:
        raise SystemExit("docker and openssl are required")
    image = run(
        [str(IMAGE_BUILDER)], cwd=ROOT, text=True, stdout=subprocess.PIPE,
    ).stdout.strip()
    suffix = f"{os.getuid()}-{os.getpid()}"
    volume = f"zulip-proxy-test-{suffix}"
    proxy = f"zulip-proxy-test-{suffix}"
    server = None
    thread = None
    try:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            certificate, key = generate_certificate(directory)
            server = ThreadingHTTPServer(("0.0.0.0", 0), ZulipHandler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            port = server.server_address[1]

            zuliprc = directory / "zuliprc"
            zuliprc.write_text(
                "[api]\n"
                f"site=https://host.docker.internal:{port}\n"
                "email=reader@example.test\n"
                "key=test-key\n",
                encoding="utf-8",
            )
            zuliprc.chmod(0o600)

            run(["docker", "volume", "create", volume], stdout=subprocess.DEVNULL)
            run([
                "docker", "run", "--rm", "--user", "0:0", "--entrypoint", "/bin/sh",
                "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxy",
                image, "-c", "chmod 1777 /run/sandbox-proxy",
            ], stdout=subprocess.DEVNULL)
            run([
                "docker", "run", "--detach", "--name", proxy,
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
                "--user", "65532:65532", "--add-host=host.docker.internal:host-gateway",
                "--entrypoint", "zulip-proxy",
                "--env", "SSL_CERT_FILE=/run/secrets/test-ca.pem",
                "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxy",
                "--mount", f"type=bind,src={zuliprc},dst=/run/secrets/zuliprc,readonly",
                "--mount", f"type=bind,src={certificate},dst=/run/secrets/test-ca.pem,readonly",
                image,
            ], stdout=subprocess.DEVNULL)

            for _ in range(100):
                ready = subprocess.run([
                    "docker", "run", "--rm", "--entrypoint", "/usr/bin/test",
                    "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxy,readonly",
                    image, "-S", "/run/sandbox-proxy/socket",
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if ready.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                logs = subprocess.run(
                    ["docker", "logs", proxy], text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                ).stdout
                raise RuntimeError(f"proxy did not become ready:\n{logs}")

            narrow = (
                "https://rust-lang.zulipchat.com/#narrow/channel/456-secret/"
                "topic/private.2Ftopic/near/789"
            )
            result = run([
                "docker", "run", "--rm", "--user", "65532:65532",
                "--entrypoint", "/src/client",
                "--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxies",
                "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxies/zulip,readonly",
                "--mount", f"type=bind,src={CLIENT},dst=/src/client,readonly",
                image, narrow, "--after", "2026-03-01", "--before", "2026-04-01",
                "--format", "jsonl",
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            messages = [json.loads(line) for line in result.stdout.splitlines()]
            assert messages == [{"id": 789, "content": "container integration"}]
            result = run([
                "docker", "run", "--rm", "--user", "65532:65532",
                "--entrypoint", "/src/client",
                "--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxies",
                "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxies/zulip,readonly",
                "--mount", f"type=bind,src={CLIENT},dst=/src/client,readonly",
                image, "456", "--list-topics", "--format", "jsonl",
            ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert json.loads(result.stdout) == {"name": "private/topic", "max_id": 789}
            assert ZulipHandler.request_error is None, ZulipHandler.request_error
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        subprocess.run(
            ["docker", "rm", "--force", proxy],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "volume", "rm", volume],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
