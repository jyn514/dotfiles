"""Real adapter requests through generated precheck headers to the actual helper.

The local projection executes generated header mutations, not Caddy's HTTP
engine. The pinned-engine test below is separate and requires existing images.
"""
from __future__ import annotations

import base64
import fnmatch
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter = load("zulip_admission_adapter", ROOT / "tools/zulip-proxy/server.py")
caddy = load("zulip_admission_caddy", ROOT / "tools/codex-sandbox/caddy_foundation.py")


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("profile-helper", timeout=3)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class AdapterPrecheckTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.socket = root / "helper.sock"
        self.token = "private-pair-token"
        self.basic = "Basic " + base64.b64encode(b"reader@example.test:helper-only-api-key").decode()
        credentials = root / "zuliprc"
        credentials.write_text("[api]\nemail=reader@example.test\nkey=helper-only-api-key\n")
        credentials.chmod(0o600)
        self.log = (root / "helper.log").open("w+")
        self.addCleanup(self.log.close)
        environment = {**os.environ, "ZULIPRC": str(credentials), "CADDY_PROFILE_TOKEN": self.token}
        self.helper = subprocess.Popen([
            sys.executable, str(ROOT / "tools/codex-sandbox/auth-proxy/profile_helper.py"),
            "--profile", "zulip", "--socket", str(self.socket),
        ], env=environment, stdout=self.log, stderr=self.log)
        self.addCleanup(self.stop_helper)
        deadline = time.monotonic() + 3
        while not self.socket.exists():
            if self.helper.poll() is not None or time.monotonic() > deadline:
                self.fail("Actual Zulip helper did not bind its disposable socket")
            time.sleep(.01)
        config = json.loads(caddy.generate_caddy_config("zulip", "example.invalid", token=self.token))
        route = config["apps"]["http"]["servers"]["egress"]["routes"][1]
        self.precheck = route["handle"][0]
        self.opener_calls = []
        self.application_calls = []
        self.helper_results = []

    def stop_helper(self):
        if self.helper.poll() is None:
            self.helper.terminate()
        self.helper.wait(timeout=3)

    def precheck_open(self, request, timeout):
        # Consume the adapter's actual HttpRequest. No fixture supplies its
        # Authorization: only the generated Caddy projection may mutate it.
        self.opener_calls.append(request)
        headers = dict(request.header_items())
        policy = self.precheck["headers"]["request"]
        for pattern in policy["delete"]:
            headers = {name: value for name, value in headers.items()
                       if not fnmatch.fnmatchcase(name.lower(), pattern.lower())}
        placeholders = {"{http.request.method}": request.method,
                        "{http.request.uri}": request.selector}
        for name, values in policy["set"].items():
            headers[name] = placeholders.get(values[0], values[0])
        connection = UnixConnection(self.socket)
        try:
            connection.request(self.precheck["rewrite"]["method"],
                self.precheck["rewrite"]["uri"].removesuffix("?"), headers=headers)
            response = connection.getresponse()
            body = response.read()
            trusted = dict(response.getheaders())
            self.helper_results.append((response.status, trusted, body))
        finally:
            connection.close()
        if response.status != 204:
            raise HTTPError(request.full_url, response.status, "helper admission rejected", trusted, io.BytesIO(body))
        self.assertEqual(trusted["Authorization"], self.basic)
        self.assertEqual(body, b"")
        self.application_calls.append((request.selector, trusted["Authorization"]))
        return io.BytesIO(json.dumps({"result": "success", "messages": [],
            "found_newest": True, "topics": [], "streams": []}).encode())

    def test_typed_adapter_requests_preserve_pair_admission_to_actual_helper(self):
        requests = (
            {"version": 1, "channel_id": 123, "topic": None,
             "anchor": "oldest", "include_anchor": True},
            {"version": 1, "operation": "channels"},
            {"version": 1, "operation": "topics", "channel_id": 123},
        )
        for token in (self.token, "wrong-pair-token", None, "", "line\nbreak", "x" * 4090):
            for request in requests:
                with self.subTest(operation=request.get("operation", "messages"),
                        admission="correct" if token == self.token else "wrong" if token == "wrong-pair-token" else "invalid"), \
                        patch.object(adapter, "CADDY_TOKEN", token), \
                        patch.object(adapter, "URL_OPEN", self.precheck_open):
                    self.opener_calls.clear(); self.application_calls.clear(); self.helper_results.clear()
                    client, server = socket.socketpair()
                    try:
                        raw = json.dumps(request, separators=(",", ":")).encode()
                        envelope = adapter.typed_broker.wrap("distinct-client-token", raw)
                        client.sendall(len(envelope).to_bytes(4, "big") + envelope)
                        client.shutdown(socket.SHUT_WR)
                        adapter.serve_connection(server, "http://test-zulip-caddy:8787/api/v1/messages", "distinct-client-token")
                        stream = client.makefile("rb")
                        try:
                            length = int.from_bytes(adapter.read_exact(stream, 4), "big")
                            result = json.loads(adapter.read_exact(stream, length))
                        finally:
                            stream.close()
                    finally:
                        client.close(); server.close()
                    if token == self.token:
                        self.assertNotIn("error", result)
                        self.assertEqual(len(self.application_calls), 1)
                        self.assertEqual(self.helper_results[0][0], 204)
                        self.assertEqual(self.opener_calls[0].get_header("Authorization"), "Bearer " + self.token)
                    elif token == "wrong-pair-token":
                        self.assertEqual(result, {"version": 1, "error": "Zulip returned HTTP 401"})
                        self.assertEqual(self.helper_results, [(401, {"Content-Length": "0"}, b"")])
                        self.assertEqual(self.application_calls, [])
                    else:
                        self.assertEqual({"version", "error"}, set(result))
                        self.assertIn("ZULIP_CADDY_TOKEN", result["error"])
                        self.assertEqual(self.opener_calls, [])
                        self.assertEqual(self.helper_results, [])
                        self.assertEqual(self.application_calls, [])
                    for secret in (self.token, "helper-only-api-key", "distinct-client-token"):
                        self.assertNotIn(secret, json.dumps(result))
        self.log.flush(); self.log.seek(0)
        logs = self.log.read()
        for secret in (self.token, "helper-only-api-key", "distinct-client-token", self.basic):
            self.assertNotIn(secret, logs)


DOCKER = "/libexec/sandbox-wrappers/docker" if Path("/libexec/sandbox-wrappers/docker").is_file() else "docker"
FIXTURE = Path(__file__).with_name("caddy_adapter_fixture.py")


class NativeAdapterCaddyTest(unittest.TestCase):
    @classmethod
    def docker(cls, *arguments, **options):
        return subprocess.run([DOCKER, *arguments], check=True, **options)

    @classmethod
    def setUpClass(cls):
        info = subprocess.run([DOCKER, "info", "--format", "{{.Architecture}}"], capture_output=True, text=True)
        if info.returncode:
            raise unittest.SkipTest("Docker runtime unavailable")
        platform = {"x86_64": "linux/amd64", "amd64": "linux/amd64",
                    "aarch64": "linux/arm64/v8", "arm64": "linux/arm64/v8"}.get(info.stdout.strip())
        if platform is None:
            raise AssertionError("Unsupported Docker engine architecture: " + info.stdout.strip())
        cls.image = "caddy@" + caddy.PLATFORMS[platform][0]
        for image in (cls.image, "python:3.12-alpine"):
            if subprocess.run([DOCKER, "image", "inspect", image], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL).returncode:
                raise unittest.SkipTest("Required unchanged local image unavailable: " + image)
        cls.identity = "zulip-admission-" + uuid.uuid4().hex[:12]
        cls.network = cls.identity
        cls.helper = cls.identity + "-helper"
        cls.proxy = cls.identity + "-zulip-caddy"
        cls.application = cls.identity + "-application"
        cls.clients = {key: cls.identity + "-" + key for key in ("correct", "wrong", "missing")}
        cls.volumes = [cls.identity + "-" + key for key in ("socket", "credentials", "config")]
        cls.token = "private-native-pair-token"
        try:
            cls.docker("network", "create", cls.network, stdout=subprocess.DEVNULL)
            for volume in cls.volumes:
                cls.docker("volume", "create", volume, stdout=subprocess.DEVNULL)
            cls.docker("run", "--pull=never", "--rm", "-i", "-v", cls.volumes[1] + ":/credentials",
                "--entrypoint", "sh", "python:3.12-alpine", "-c", "cat > /credentials/zuliprc && chmod 600 /credentials/zuliprc",
                input=b"[api]\nemail=reader@example.test\nkey=helper-only-native-api-key\n")
            cls.docker("create", "--pull=never", "--name", cls.helper, "--network", "none",
                "--env", "CADDY_PROFILE_TOKEN=" + cls.token, "--env", "ZULIPRC=/credentials/zuliprc",
                "-v", cls.volumes[0] + ":/run/profile-helper", "-v", cls.volumes[1] + ":/credentials:ro",
                "--entrypoint", "python3", "python:3.12-alpine", "/profile_helper.py", "--profile", "zulip",
                stdout=subprocess.DEVNULL)
            cls.docker("cp", str(ROOT / "tools/codex-sandbox/auth-proxy/profile_helper.py"), cls.helper + ":/profile_helper.py")
            cls.docker("start", cls.helper, stdout=subprocess.DEVNULL)
            cls.docker("create", "--pull=never", "--name", cls.application, "--network", cls.network,
                "--network-alias", "application", "--entrypoint", "python3", "python:3.12-alpine",
                "/fixture.py", "application", stdout=subprocess.DEVNULL)
            cls.docker("cp", str(FIXTURE), cls.application + ":/fixture.py")
            cls.docker("start", cls.application, stdout=subprocess.DEVNULL)
            value = json.loads(caddy.generate_caddy_config("zulip", "application", token=cls.token))
            upstream = value["apps"]["http"]["servers"]["egress"]["routes"][1]["handle"][-1]
            upstream["upstreams"] = [{"dial": "application:8082"}]
            upstream["transport"] = {"protocol": "http"}
            cls.docker("run", "--pull=never", "--rm", "-i", "-v", cls.volumes[2] + ":/config", cls.image,
                "sh", "-c", "cat > /config/caddy.json", input=json.dumps(value).encode())
            cls.docker("run", "--pull=never", "-d", "--name", cls.proxy, "--network", cls.network,
                "-v", cls.volumes[0] + ":/run/profile-helper:ro", "-v", cls.volumes[2] + ":/config:ro",
                cls.image, "caddy", "run", "--config", "/config/caddy.json", stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + 8
            while True:
                ready = subprocess.run([DOCKER, "exec", cls.proxy, "wget", "-qO-",
                    "--header=Authorization: Bearer " + cls.token, "http://127.0.0.1:8787/ready"], capture_output=True)
                if ready.returncode == 0:
                    break
                if time.monotonic() > deadline:
                    raise AssertionError("Actual Caddy/helper did not become ready: " + ready.stderr.decode(errors="replace"))
                time.sleep(.05)
            for key, name in cls.clients.items():
                environment = ["--env", "ZULIP_BROKER_KEY=distinct-native-client-token", "--env",
                    "ZULIP_CADDY_ENDPOINT=http://" + cls.proxy + ":8787/api/v1/messages"]
                if key != "missing":
                    environment += ["--env", "ZULIP_CADDY_TOKEN=" + (cls.token if key == "correct" else "wrong-native-pair-token")]
                cls.docker("create", "--pull=never", "--name", name, "--network", cls.network, *environment,
                    "--entrypoint", "sh", "python:3.12-alpine", "-c", "sleep 600", stdout=subprocess.DEVNULL)
                for path, destination in ((ROOT / "tools/zulip-proxy/server.py", "/adapter/server.py"),
                        (ROOT / "tools/zulip-proxy/protocol.json", "/adapter/protocol.json"),
                        (ROOT / "tools/codex-sandbox/auth-proxy/typed_broker.py", "/adapter/typed_broker.py"),
                        (FIXTURE, "/fixture.py")):
                    if destination.startswith("/adapter/"):
                        cls.docker("cp", "-", name + ":/", input=cls.tar_entry(destination.removeprefix("/"), path.read_bytes()))
                    else:
                        cls.docker("cp", str(path), name + ":" + destination)
                cls.docker("start", name, stdout=subprocess.DEVNULL)
        except BaseException:
            cls.cleanup()
            raise

    @staticmethod
    def tar_entry(name, data):
        import tarfile
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            if "/" in name:
                directory = tarfile.TarInfo(name.rsplit("/", 1)[0]); directory.type = tarfile.DIRTYPE
                directory.mode = 0o755; archive.addfile(directory)
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o600
            archive.addfile(info, io.BytesIO(data))
        return output.getvalue()

    @classmethod
    def cleanup(cls):
        for name in (cls.helper, cls.proxy, cls.application, *cls.clients.values()):
            subprocess.run([DOCKER, "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for volume in cls.volumes:
            subprocess.run([DOCKER, "volume", "rm", volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([DOCKER, "network", "rm", cls.network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def state(self):
        return json.loads(self.docker("exec", self.application, "wget", "-qO-",
            "http://127.0.0.1:8082/state", capture_output=True).stdout)

    def test_all_typed_operations_traverse_actual_adapter_caddy_and_helper(self):
        requests = ({"version": 1, "channel_id": 123, "topic": None, "anchor": "oldest", "include_anchor": True},
                    {"version": 1, "operation": "channels"},
                    {"version": 1, "operation": "topics", "channel_id": 123})
        basic = "Basic " + base64.b64encode(b"reader@example.test:helper-only-native-api-key").decode()
        for admission, client in self.clients.items():
            for request in requests:
                with self.subTest(admission=admission, operation=request.get("operation", "messages")):
                    self.docker("exec", self.application, "wget", "-qO-", "http://127.0.0.1:8082/reset", stdout=subprocess.DEVNULL)
                    raw = json.dumps(request, separators=(",", ":")).encode()
                    envelope = adapter.typed_broker.wrap("distinct-native-client-token", raw)
                    framed = len(envelope).to_bytes(4, "big") + envelope
                    output = self.docker("exec", "-i", client, "python3", "/fixture.py", "adapter",
                        input=framed, capture_output=True)
                    self.assertEqual(output.stderr, b"")
                    self.assertEqual(int.from_bytes(output.stdout[:4], "big"), len(output.stdout[4:]))
                    result = json.loads(output.stdout[4:]); state = self.state()
                    if admission == "correct":
                        self.assertNotIn("error", result)
                        self.assertEqual(len(state), 1)
                        self.assertEqual(state[0]["authorization"], basic)
                        self.assertEqual(state[0]["body_length"], "0")
                    elif admission == "wrong":
                        self.assertEqual(result, {"version": 1, "error": "Zulip returned HTTP 401"})
                        self.assertEqual(state, [])
                    else:
                        self.assertEqual({"version", "error"}, set(result))
                        self.assertIn("ZULIP_CADDY_TOKEN", result["error"])
                        self.assertEqual(state, [])
                    for secret in (self.token, "distinct-native-client-token", "helper-only-native-api-key", basic):
                        self.assertNotIn(secret, output.stdout.decode())
        logs = b""
        for name in (self.helper, self.proxy):
            output = self.docker("logs", name, capture_output=True)
            logs += output.stdout + output.stderr
        for secret in (self.token, "distinct-native-client-token", "helper-only-native-api-key", basic):
            self.assertNotIn(secret.encode(), logs)


if __name__ == "__main__":
    unittest.main()
