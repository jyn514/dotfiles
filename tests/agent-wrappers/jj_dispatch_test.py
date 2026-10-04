#!/usr/bin/env python3
"""Exercise the real wrapper/router handoff, with recording execution backends."""
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "libexec/agent-wrappers/jj"
HELPER = ROOT / "tools/jj-proxy/route.py"
RECORDER = Path(__file__).with_name("fixtures") / "jj_record.py"
NATIVE = (os.environ.get("DOTFILES_TEST_JJ_REAL") or os.environ.get("JJ_REAL")
          or shutil.which("jj"))


class JjDispatchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jj-dispatch-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.record = self.root / "record.jsonl"
        for role in ("native", "proxy"):
            target = self.root / role
            subprocess.run(["cp", str(RECORDER), str(target)], check=True)
            subprocess.run(["cmp", str(RECORDER), str(target)], check=True)
            target.chmod(0o755)
        self.wrapper = self.root / "jj"
        self.wrapper.write_text(WRAPPER.read_text().replace(
            "/libexec/agent-wrappers/jj-proxy-client", str(self.root / "proxy")))
        self.wrapper.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "home/.config"),
            "JJ_CONFIG": str(self.root / "config.toml"),
            "JJ_AGENT": "", "PI_CODING_AGENT": "", "CLAUDECODE": "",
            "CODEX_THREAD_ID": "", "JJ_USER": "TestAgent", "JJ_EMAIL": "agent@example.invalid",
            "JJ_REAL": str(self.root / "native"), "JJ_ROUTE_HELPER": str(HELPER),
            "JJ_PROXY_REPO": str(ROOT),
            "SANDBOX_PROXY_DIR": str(self.root / "socket-volume"),
            "SANDBOX_PROXY_DEFAULT_DIR": str(self.root / "no-default"),
            "JJ_TEST_RECORD": str(self.record),
        }
        self.env.pop("PI_CALL_MODEL", None)
        (self.root / "config.toml").write_text("")

    def repo(self, name="local"):
        if not NATIVE:
            self.skipTest("native JJ is required for real metadata fixtures")
        destination = self.root / name
        destination.mkdir()
        env = {**self.env, "JJ_REAL": str(NATIVE)}
        result = subprocess.run([str(NATIVE), "git", "init", "."], cwd=destination,
                                env=env, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return destination

    def run_wrapper(self, *args, cwd=None, env=None):
        return subprocess.run([str(self.wrapper), *args], cwd=cwd or self.root,
                              env=env or self.env, text=True, capture_output=True)

    def calls(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def test_local_commit_uses_native_and_scopes_both_hooks_to_selected_workspace(self):
        selected = self.repo()
        result = self.run_wrapper("--repository", str(selected), "commit", "-m", "literal ; $() message", cwd=ROOT)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls()
        self.assertEqual(["native"] * 3, [call["role"] for call in calls])
        self.assertEqual(["--repository", str(selected)], calls[0]["argv"][:2])
        self.assertEqual(["--repository", str(selected)], calls[2]["argv"][:2])
        self.assertEqual(["--repository", str(selected), "commit", "-m", "literal ; $() message"], calls[1]["argv"][-5:])
        self.assertTrue(all(call["cwd"] == str(ROOT) for call in calls))

    def test_no_working_copy_and_historical_modes_suppress_both_hooks(self):
        selected = self.repo()
        for flags in (["--ignore-working-copy"], ["--at-operation", "old-op"], ["-@old-op"]):
            with self.subTest(flags=flags):
                self.record.unlink(missing_ok=True)
                result = self.run_wrapper("-R", str(selected), *flags, "commit", "-m", "message", cwd=ROOT)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(self.calls()))
                self.assertNotIn("metaedit", self.calls()[0]["argv"])

    def test_bootstrap_alias_routes_by_destination_and_never_stamps_invoking_repo(self):
        (self.root / "config.toml").write_text('[aliases]\nprepare = ["git", "init"]\n')
        destination = self.root / "not-yet-created"
        result = self.run_wrapper("prepare", str(destination), cwd=ROOT)
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self.calls()
        self.assertEqual(["native", "native"], [call["role"] for call in calls])
        self.assertEqual(["prepare", str(destination)], calls[0]["argv"][-2:])
        self.assertEqual(["--repository", str(destination)], calls[1]["argv"][:2])

    def test_leading_selector_keeps_plain_noninteractive_diff(self):
        selected = self.repo()
        result = self.run_wrapper("-R" + str(selected), "diff", "--name-only")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ui.diff-formatter=:git", self.calls()[0]["argv"])
        self.record.unlink()
        result = self.run_wrapper("-R", str(selected), "diff", "--config", "ui.diff-formatter=:summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("ui.diff-formatter=:git", self.calls()[0]["argv"])

    def test_failed_primary_native_command_retains_status_without_cleanup(self):
        selected = self.repo()
        result = self.run_wrapper("commit", "-m", "message", cwd=selected,
                                  env={**self.env, "JJ_TEST_MAIN_EXIT": "7", "JJ_TEST_HOOK_EXIT": "8"})
        self.assertEqual(7, result.returncode, result.stderr)
        self.assertEqual(2, len(self.calls()))

    def test_failed_proxy_is_never_retried_natively(self):
        for status in (2, 125):
            with self.subTest(status=status):
                self.record.unlink(missing_ok=True)
                args = ["status", "--no-pager"]
                result = self.run_wrapper(*args, cwd=ROOT, env={**self.env, "JJ_TEST_MAIN_EXIT": str(status)})
                self.assertEqual(status, result.returncode, result.stderr)
                self.assertEqual(["proxy"], [call["role"] for call in self.calls()])
                self.assertEqual(args, self.calls()[0]["argv"])

    def test_guest_workspace_with_host_store_reports_namespace_error_without_native_retry(self):
        linked = self.root / "linked"
        (linked / ".jj").mkdir(parents=True)
        (linked / ".jj/repo").write_text(str(ROOT / ".jj/repo"))
        self.wrapper.write_text(WRAPPER.read_text().replace(
            "/libexec/agent-wrappers/jj-proxy-client", str(ROOT / "tools/jj-proxy/client")))
        result = self.run_wrapper("status", cwd=linked)
        self.assertEqual(125, result.returncode, result.stderr)
        self.assertIn("run from the mounted workspace", result.stderr)
        self.assertEqual([], self.calls())

    def test_per_call_pi_model_overrides_shared_state_on_native_and_proxy(self):
        local = self.repo()
        model = self.root / "shared-model.json"
        model.write_text(json.dumps({"session_id": "s", "provider": "provider",
                                     "modelId": "stale-shared-model"}))
        env = {**self.env, "JJ_AGENT": "pi", "PI_MODEL": "stale-env-model",
               "PI_MODEL_FILE": str(model), "PI_MODEL_SESSION_ID": "s"}
        # Reuse the same shared file while independent calls select different models.
        # Whitespace and shell punctuation are safe under the existing ID policy.
        for role, cwd in (("native", local), ("proxy", ROOT)):
            for name in ("call-model-A", "call-model-B ; $()", " spaced model "):
                with self.subTest(role=role, model=name):
                    self.record.unlink(missing_ok=True)
                    args = ["status", "--no-pager"]
                    result = self.run_wrapper(*args, cwd=cwd,
                                              env={**env, "PI_CALL_MODEL": name})
                    self.assertEqual(0, result.returncode, result.stderr)
                    calls = self.calls()
                    self.assertEqual(role, calls[0]["role"])
                    self.assertEqual(args, calls[0]["argv"])
                    self.assertEqual("Pi " + name, calls[0]["user"])
                    self.assertEqual("325577925+one-esk-nineteen@users.noreply.github.com",
                                     calls[0]["email"])
                    self.assertNotIn("could not determine active Pi model", result.stderr)

    def test_unknown_call_pi_model_never_falls_back_on_native_or_proxy(self):
        local = self.repo()
        model = self.root / "shared-model.json"
        model.write_text(json.dumps({"session_id": "s", "provider": "provider",
                                     "modelId": "stale-shared-model"}))
        env = {**self.env, "JJ_AGENT": "pi", "PI_MODEL": "stale-env-model",
               "PI_MODEL_FILE": str(model), "PI_MODEL_SESSION_ID": "s"}
        for role, cwd in (("native", local), ("proxy", ROOT)):
            for name in ("", "bad\nmodel", "bad\rmodel", "bad\tmodel", "bad\x1fmodel", "bad\x7fmodel"):
                with self.subTest(role=role, model=name):
                    self.record.unlink(missing_ok=True)
                    args = ["status", "--no-pager"]
                    result = self.run_wrapper(*args, cwd=cwd,
                                              env={**env, "PI_CALL_MODEL": name})
                    self.assertEqual(0, result.returncode, result.stderr)
                    calls = self.calls()
                    self.assertEqual(role, calls[0]["role"])
                    self.assertEqual(args, calls[0]["argv"])
                    self.assertEqual("Pi unknown-model", calls[0]["user"])
                    self.assertEqual("325577925+one-esk-nineteen@users.noreply.github.com",
                                     calls[0]["email"])
                    self.assertIn("could not determine active Pi model", result.stderr)

    def test_absent_call_pi_model_keeps_legacy_session_and_id_validation(self):
        model = self.root / "shared-model.json"
        env = {**self.env, "JJ_AGENT": "pi", "PI_MODEL": "stale-env-model",
               "PI_MODEL_FILE": str(model), "PI_MODEL_SESSION_ID": "s"}
        valid = {"session_id": "s", "provider": "provider", "modelId": "legacy-model"}
        cases = [(valid, "Pi legacy-model")]
        for fields in ({"session_id": "other-session"}, {"provider": ""},
                       {"modelId": ""}, {"modelId": None}, {"modelId": 7},
                       {"modelId": "bad\nmodel"}, {"modelId": "bad\x7fmodel"}):
            cases.append(({**valid, **fields}, "Pi unknown-model"))
        for contents, identity in cases:
            with self.subTest(contents=contents):
                self.record.unlink(missing_ok=True)
                model.write_text(json.dumps(contents))
                result = self.run_wrapper("status", "--no-pager", cwd=ROOT, env=env)
                self.assertEqual(0, result.returncode, result.stderr)
                call = self.calls()[0]
                self.assertEqual("proxy", call["role"])
                self.assertEqual(["status", "--no-pager"], call["argv"])
                self.assertEqual(identity, call["user"])
                self.assertEqual(identity == "Pi unknown-model",
                                 "could not determine active Pi model" in result.stderr)

    def test_private_split_is_opaque_proxy_only_and_uses_runtime_pi_identity(self):
        model = self.root / "model.json"
        model.write_text(json.dumps({"session_id": "s", "provider": "provider", "modelId": "active-model"}))
        env = {**self.env, "JJ_AGENT": "pi", "PI_MODEL_FILE": str(model), "PI_MODEL_SESSION_ID": "s"}
        env.pop("JJ_USER")
        env.pop("JJ_EMAIL")
        args = ["--agent-split", "patch-file", "--repository=/literal/message", "-Rliteral-revision"]
        result = self.run_wrapper(*args, cwd=ROOT, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["proxy"], [call["role"] for call in self.calls()])
        self.assertEqual(args, self.calls()[0]["argv"])
        self.assertEqual("Pi active-model", self.calls()[0]["user"])
        self.record.unlink()
        local = self.repo()
        result = self.run_wrapper(*args, cwd=local, env=env)
        self.assertEqual(125, result.returncode)
        self.assertIn("proxy-only", result.stderr)
        self.assertEqual([], self.calls())

    def test_private_split_runtime_identity_reaches_actual_client_request(self):
        repository = self.root / "protected-role"
        repository.mkdir()
        patch = repository / "patch"
        patch.write_text("literal patch bytes\n")
        model = self.root / "model.json"
        model.write_text(json.dumps({"session_id": "s", "provider": "provider", "modelId": "wire-model"}))
        socket_path = self.root / "socket-volume/jj/socket"
        socket_path.parent.mkdir(parents=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.settimeout(5)
        listener.bind(str(socket_path))
        listener.listen(1)
        self.addCleanup(listener.close)
        requests, errors = [], []

        def serve():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)

                    def receive(length):
                        data = bytearray()
                        while len(data) < length:
                            chunk = connection.recv(length - len(data))
                            if not chunk:
                                raise RuntimeError("request ended early")
                            data.extend(chunk)
                        return bytes(data)

                    length = struct.unpack(">I", receive(4))[0]
                    requests.append(json.loads(receive(length)))
                    response = json.dumps({"version": 1, "exit": 0, "stdout": "split-ok\n", "stderr": ""}).encode()
                    connection.sendall(struct.pack(">I", len(response)) + response)
            except Exception as error:
                errors.append(error)

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        self.wrapper.write_text(WRAPPER.read_text().replace(
            "/libexec/agent-wrappers/jj-proxy-client", str(ROOT / "tools/jj-proxy/client")))
        env = {**self.env, "JJ_PROXY_REPO": str(repository), "JJ_AGENT": "pi",
               "PI_MODEL_FILE": str(model), "PI_MODEL_SESSION_ID": "s"}
        env.pop("JJ_USER")
        env.pop("JJ_EMAIL")
        message, revision = "--repository=/literal/message", "-Rliteral-revision"
        result = self.run_wrapper("--agent-split", str(patch), message, revision, cwd=repository, env=env)
        server.join(timeout=6)
        self.assertFalse(server.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("split-ok\n", result.stdout)
        self.assertEqual([], self.calls())
        self.assertEqual(1, len(requests))
        self.assertEqual("Pi wire-model", requests[0]["user"])
        self.assertEqual("325577925+one-esk-nineteen@users.noreply.github.com", requests[0]["email"])
        self.assertEqual([], requests[0]["argv"])
        self.assertEqual({"patch": patch.read_text(), "message": message, "revision": revision}, requests[0]["agent_split"])

    def test_private_split_bad_arity_and_missing_helper_have_no_backend_effects(self):
        result = self.run_wrapper("--agent-split", "patch", "message", cwd=ROOT)
        self.assertEqual(125, result.returncode)
        self.assertEqual([], self.calls())
        result = self.run_wrapper("status", env={**self.env, "JJ_ROUTE_HELPER": str(self.root / "missing")})
        self.assertEqual(125, result.returncode)
        self.assertIn("helper is missing", result.stderr)
        self.assertEqual([], self.calls())

    def test_failed_or_malformed_route_publication_never_reaches_a_backend(self):
        for mode, status in (("failed", 9), ("duplicate", 125), ("relative", 125)):
            with self.subTest(mode=mode):
                result = self.run_wrapper("status", env={
                    **self.env, "JJ_ROUTE_HELPER": str(RECORDER.with_name("route_output.py")),
                    "JJ_TEST_ROUTE_MODE": mode,
                })
                self.assertEqual(status, result.returncode, result.stderr)
                self.assertEqual([], self.calls())

    def test_stripped_proxy_env_still_routes_local_repository_natively(self):
        local = self.repo()
        volume = self.root / "socket-volume"
        (volume / "jj").mkdir(parents=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(volume / "jj/socket"))
        self.addCleanup(listener.close)
        env = {**self.env, "SANDBOX_PROXY_DEFAULT_DIR": str(volume)}
        env.pop("SANDBOX_PROXY_DIR")
        result = self.run_wrapper("status", cwd=local, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(all(call["role"] == "native" for call in self.calls()))
        self.assertEqual(str(volume), self.calls()[0]["proxy"])

    def test_real_native_commit_with_active_proxy_preserves_pi_attribution(self):
        local = self.repo()
        (local / "file").write_text("local work\n")
        model = self.root / "model.json"
        (self.root / "config.toml").write_text('[user]\nname="Repository User"\nemail="repository@example.invalid"\n')
        env = {**self.env, "JJ_REAL": str(NATIVE), "JJ_AGENT": "pi",
               "PI_MODEL_FILE": str(model), "PI_MODEL_SESSION_ID": "s"}
        env.pop("JJ_USER")
        env.pop("JJ_EMAIL")
        for name in ("first-model", "second-model"):
            with self.subTest(model=name):
                if name == "second-model":
                    env.update(JJ_USER="old-exported-agent", JJ_EMAIL="old@example.invalid")
                model.write_text(json.dumps({"session_id": "s", "provider": "provider", "modelId": name}))
                (local / "file").write_text(name + "\n")
                # Trailing configs previously discarded leading identity configs.
                result = self.run_wrapper("commit", "--config", "ui.color=never", "-m", name, cwd=local, env=env)
                self.assertEqual(0, result.returncode, result.stderr)
                result = subprocess.run([str(NATIVE), "log", "--ignore-working-copy", "-r", "@-", "--no-graph",
                                         "-T", 'author.name() ++ "\\n" ++ committer.name()'],
                                        cwd=local, env=env, text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["Pi " + name] * 2, result.stdout.splitlines())
                result = subprocess.run([str(NATIVE), "log", "--ignore-working-copy", "-r", "@", "--no-graph",
                                         "-T", 'author.name()'],
                                        cwd=local, env=env, text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("Repository User", result.stdout)
        self.assertEqual([], self.calls())


if __name__ == "__main__":
    unittest.main()
