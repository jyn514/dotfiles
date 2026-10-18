from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / "tools" / "jj-proxy" / "client"


def receive_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise RuntimeError("request ended early")
        result.extend(chunk)
    return bytes(result)


class JjProxyClientTest(unittest.TestCase):
    def run_client(self, arguments: list[str], *, files: dict[str, str] | None = None,
                   location="active", inspect=False, response_version=2,
                   symlink=False) -> tuple[subprocess.CompletedProcess[str], dict]:
        # The wire contract addresses physical /src paths, not arbitrary host
        # temporary paths. All fixture writes remain in disposable storage.
        if Path('/src') not in ROOT.parents:
            self.skipTest('wire protocol fixture requires checkout under /src')
        target = ROOT / "target"
        target.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target, prefix="jj-client-") as temporary:
            root = Path(temporary)
            repository = root / "active"
            repository.mkdir()
            self.current = root / location / "nested"
            self.current.mkdir(parents=True)
            invocation_cwd = self.current
            if symlink:
                invocation_cwd = root / "cwd-alias"
                invocation_cwd.symlink_to(self.current, target_is_directory=True)
            for name, contents in (files or {}).items():
                (self.current.parent / name).write_text(contents)
            socket_directory = root / "proxies" / "jj"
            socket_directory.mkdir(parents=True)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.settimeout(5)
            listener.bind(str(socket_directory / "socket"))
            listener.listen(1)
            request: dict = {}
            errors = []

            def serve() -> None:
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(5)
                        length = struct.unpack(">I", receive_exact(connection, 4))[0]
                        request.update(json.loads(receive_exact(connection, length)))
                        response = json.dumps({
                            "version": response_version, "exit": 7, "stdout": "output\n", "stderr": "warning\n",
                        }).encode()
                        connection.sendall(struct.pack(">I", len(response)) + response)
                except Exception as error:
                    errors.append(error)

            server = threading.Thread(target=serve, daemon=True)
            server.start()
            environment = {
                **os.environ,
                "SANDBOX_PROXY_DIR": str(root / "proxies"),
                "JJ_PROXY_REPO": str(repository),
                "JJ_PROXY_INSPECT": "1" if inspect else "",
                "JJ_USER": "Codex gpt-test",
                "JJ_EMAIL": "codex@example.test",
                "PWD": str(invocation_cwd),
            }
            expanded = [str(self.current.parent / argument.removeprefix("REPO/")) if argument.startswith("REPO/") else argument for argument in arguments]
            result = subprocess.run(
                [str(CLIENT), *expanded], cwd=invocation_cwd, env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            )
            server.join(timeout=6)
            listener.close()
            self.assertFalse(server.is_alive())
            self.assertEqual([], errors)
            return result, request

    def test_forwards_absolute_cwd_arguments_and_response(self) -> None:
        result, request = self.run_client(["status", "--quiet"])
        self.assertEqual(7, result.returncode)
        self.assertEqual("output\n", result.stdout)
        self.assertEqual("warning\n", result.stderr)
        self.assertEqual({
            "version": 2,
            "mode": "mutate",
            "cwd": str(self.current),
            "argv": ["status", "--quiet"],
            "user": "Codex gpt-test",
            "email": "codex@example.test",
        }, request)

    def test_symlink_cwd_sends_physical_path_not_shell_pwd(self) -> None:
        result, request = self.run_client(["status"], location="relocated-config", symlink=True)
        self.assertEqual(7, result.returncode, result.stderr)
        self.assertEqual(str(self.current), request["cwd"])
        self.assertEqual("mutate", request["mode"])

    def test_selector_and_fileset_do_not_rebase_invocation_cwd(self) -> None:
        for selector in ("../other", "/src/relocated-dotfiles"):
            with self.subTest(selector=selector):
                args = ["-R", selector, "commit", "root:skills/example", "-m", "change"]
                result, request = self.run_client(args)
                self.assertEqual(7, result.returncode, result.stderr)
                self.assertEqual("mutate", request["mode"])
                self.assertEqual(str(self.current), request["cwd"])
                self.assertEqual(args, request["argv"])

    def test_sibling_cwd_requests_mutation_unless_explicit_inspection(self) -> None:
        # Permission is resolved by the server, never by this client's active
        # repository role. Relocating dotfiles must not require a client edit.
        for location in ("dotfiles", "relocated-config", "unlisted-sibling"):
            for inspect in (False, True):
                with self.subTest(location=location, inspect=inspect):
                    result, request = self.run_client(["status"], location=location, inspect=inspect)
                    self.assertEqual(7, result.returncode, result.stderr)
                    self.assertEqual("inspect" if inspect else "mutate", request["mode"])
                    self.assertEqual(str(self.current), request["cwd"])

    def test_encodes_agent_split_from_dotfiles_as_a_dedicated_operation(self) -> None:
        patch = "diff --git a/note b/note\n--- a/note\n+++ b/note\n"
        result, request = self.run_client(
            ["--agent-split", "REPO/selected.patch", "Extract note", "@"],
            files={"selected.patch": patch}, location="dotfiles",
        )
        self.assertEqual(7, result.returncode, result.stderr)
        self.assertEqual(str(self.current), request["cwd"])
        self.assertEqual("mutate", request["mode"])
        self.assertEqual([], request["argv"])
        self.assertEqual({"patch": patch, "message": "Extract note", "revision": "@"}, request["agent_split"])

    def test_old_response_is_rejected_without_publishing_its_output(self) -> None:
        result, request = self.run_client(["status"], response_version=1)
        self.assertEqual(2, request["version"])
        self.assertEqual(125, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("unsupported or malformed proxy response", result.stderr)

    def test_outside_source_cwd_is_rejected_even_if_selected_or_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary)
            for inspect in ("", "1"):
                with self.subTest(inspect=inspect):
                    result = subprocess.run([str(CLIENT), "status"], cwd=outside,
                                            env={**os.environ, "SANDBOX_PROXY_DIR": str(outside),
                                                 "JJ_PROXY_REPO": str(outside), "JJ_PROXY_INSPECT": inspect},
                                            text=True, capture_output=True, timeout=5)
                    self.assertEqual(125, result.returncode)
                    self.assertEqual("", result.stdout)
                    self.assertIn("run from the mounted workspace", result.stderr)


if __name__ == "__main__":
    unittest.main()
