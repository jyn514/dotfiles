#!/usr/bin/env python3
"""Exercise the real wrapper/router handoff, with recording execution backends."""
import json
import os
import pty
from pathlib import Path
import shutil
import signal
import time
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
        subprocess.run(["cp", str(WRAPPER), str(self.wrapper)], check=True)
        subprocess.run(["cmp", str(WRAPPER), str(self.wrapper)], check=True)
        self.wrapper.write_text(self.wrapper.read_text().replace(
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
        self.env.pop("JJ_PROXY_ROOTS", None)
        self.env.pop("JJ_PROXY_INSPECT", None)
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

    def discovery_wrapper(self, mode):
        layout = self.root / ("discovery-" + mode)
        checkout = layout / "source checkout"
        wrapper = checkout / "libexec/agent-wrappers/jj"
        wrapper.parent.mkdir(parents=True)
        subprocess.run(["cp", str(self.root / "jj"), str(wrapper)], check=True)
        subprocess.run(["cmp", str(self.root / "jj"), str(wrapper)], check=True)
        wrapper.chmod(0o755)
        helper = checkout / "tools/jj-proxy/route.py"
        helper.parent.mkdir(parents=True)
        subprocess.run(["cp", str(HELPER), str(helper)], check=True)
        subprocess.run(["cmp", str(HELPER), str(helper)], check=True)
        if mode == "direct":
            return wrapper
        aliases = layout / "aliases with spaces"
        aliases.mkdir()
        entry = aliases / "jj"
        if mode == "absolute":
            entry.symlink_to(wrapper)
        else:
            entry.symlink_to("middle")
            (aliases / "middle").symlink_to("../source checkout/libexec/agent-wrappers/jj")
        return entry

    def test_source_helper_discovery_preserves_direct_and_symlink_invocations(self):
        for mode in ("direct", "absolute", "relative-chain"):
            with self.subTest(mode=mode):
                self.record.unlink(missing_ok=True)
                self.wrapper = self.discovery_wrapper(mode)
                env = dict(self.env)
                env.pop("JJ_ROUTE_HELPER")
                result = subprocess.run([
                    shutil.which("python3"), str(RECORDER.with_name("jj_source_bootstrap.py")),
                    "discover", str(self.wrapper), "status", "--no-pager",
                ], cwd=ROOT, env=env, text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["proxy"], [call["role"] for call in self.calls()])
                self.assertEqual(["status", "--no-pager"], self.calls()[0]["argv"])

    def test_filesystem_resolution_failure_never_reaches_a_backend(self):
        # Compile first, unlink the real path, then execute unchanged code.
        # Discovery must reject that missing invocation path before any backend.
        wrapper = self.discovery_wrapper("direct")
        env = dict(self.env)
        env.pop("JJ_ROUTE_HELPER")
        result = subprocess.run([
            shutil.which("python3"), str(RECORDER.with_name("jj_source_bootstrap.py")),
            "unlink", str(wrapper), "status",
        ], cwd=ROOT, env=env, text=True, capture_output=True)
        self.assertEqual(125, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertIn("No such file", result.stderr)
        self.assertEqual([], self.calls())

    def test_native_unusual_paths_and_operands_survive_without_shell_interpretation(self):
        names = ["tab\tname", "line\nname", "trailing\n", "quote'\"name",
                 "back\\slash", "literal\\c", "$(touch marker)", "`touch marker`"]
        for index, name in enumerate(names):
            with self.subTest(name=name):
                selected = self.repo(name)
                alias = self.root / ("alias-" + str(index))
                alias.symlink_to(selected)
                self.record.unlink(missing_ok=True)
                message = name + " message\n"
                argv = ["--repository", str(alias), "commit", "-m", message]
                result = self.run_wrapper(*argv)
                self.assertEqual(0, result.returncode, result.stderr)
                calls = self.calls()
                self.assertEqual(3, len(calls))
                self.assertEqual(argv, calls[1]["argv"])
                for hook in (calls[0], calls[2]):
                    self.assertEqual(["--repository", str(selected)], hook["argv"][:2])
                    self.assertEqual(str(self.root), hook["cwd"])
                self.assertFalse((self.root / "marker").exists())

    def test_empty_route_command_and_absent_target_are_usable(self):
        for mode in ("empty", "empty-command"):
            with self.subTest(mode=mode):
                self.record.unlink(missing_ok=True)
                result = self.run_wrapper("status", env={
                    **self.env, "JJ_ROUTE_HELPER": str(RECORDER.with_name("route_output.py")),
                    "JJ_TEST_ROUTE_MODE": mode,
                })
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([["status"]], [call["argv"] for call in self.calls()])

    def test_standalone_path_cleanup_removes_invoked_directory_and_canonical_aliases(self):
        # No helper, no socket: Python alone is enough even without jq/realpath.
        commands = self.root / "commands"
        commands.mkdir()
        (commands / "python3").symlink_to(shutil.which("python3"))
        backend = self.root / "backend"
        backend.mkdir()
        subprocess.run(["cp", str(RECORDER), str(backend / "jj")], check=True)
        subprocess.run(["cmp", str(RECORDER), str(backend / "jj")], check=True)
        (backend / "jj").chmod(0o755)
        aliases = self.root / "alias-bin"
        aliases.mkdir()
        (aliases / "jj").symlink_to(self.wrapper)
        alias_alias = self.root / "alias-alias"
        alias_alias.symlink_to(aliases)
        env = {**self.env, "JJ_USER": "", "JJ_ROUTE_HELPER": "", "SANDBOX_PROXY_DIR": "",
               "JJ_REAL": "", "PATH": os.pathsep.join(map(str, [aliases, alias_alias,
                    self.root / "missing", backend, commands])) + ":"}
        result = subprocess.run([str(aliases / "jj"), "status", "literal\noperand"],
                                cwd=self.root, env=env, text=True, capture_output=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["jj"], [call["role"] for call in self.calls()])
        self.assertEqual(["status", "literal\noperand"], self.calls()[0]["argv"])

    def test_standalone_does_not_import_router_dependencies(self):
        env = {**self.env, "JJ_ROUTE_HELPER": "", "SANDBOX_PROXY_DIR": "", "JJ_USER": ""}
        fixture = RECORDER.with_name("jj_without_router.py")
        result = subprocess.run([shutil.which("python3"), str(fixture), str(self.wrapper), "status"],
                                cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["native"], [call["role"] for call in self.calls()])

    def check_native_cancellation(self, *, group):
        selected = self.repo()
        fixture = RECORDER.with_name("jj_signal_backend.py")
        backend = self.root / "signal-native"
        subprocess.run(["cp", str(fixture), str(backend)], check=True)
        subprocess.run(["cmp", str(fixture), str(backend)], check=True)
        backend.chmod(0o755)
        for phase, count in (("pre", 1), ("main", 2), ("post", 3)):
            for exits_zero in (False, True):
                with self.subTest(phase=phase, exits_zero=exits_zero):
                    record, ready = self.root / "signal.jsonl", self.root / "signal.ready"
                    record.unlink(missing_ok=True)
                    ready.unlink(missing_ok=True)
                    child = subprocess.Popen(
                        [str(self.wrapper), "commit", "-m", "cancelled"], cwd=selected,
                        env={**self.env, "JJ_REAL": str(backend), "JJ_SIGNAL_PHASE": phase,
                             "JJ_SIGNAL_RECORD": str(record), "JJ_SIGNAL_READY": str(ready),
                             "JJ_SIGNAL_EXIT_ZERO": "1" if exits_zero else ""},
                        start_new_session=True, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True)
                    try:
                        deadline = time.monotonic() + 5
                        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                            time.sleep(0.005)
                        self.assertTrue(ready.exists(), "backend did not reach selected phase")
                        if group:
                            os.killpg(child.pid, signal.SIGTERM)
                        else:
                            child.send_signal(signal.SIGTERM)
                        stdout, stderr = child.communicate(timeout=5)
                        self.assertEqual(-signal.SIGTERM, child.returncode, stderr)
                        self.assertEqual("", stdout)
                        calls = [json.loads(line) for line in record.read_text().splitlines()]
                        self.assertEqual(count, len(calls), calls)
                        # Completion includes reaping the owned native child, even
                        # when its signal handler elects to return success.
                        pid = int(ready.read_text())
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline:
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                break
                            time.sleep(0.01)
                        else:
                            self.fail("cancelled native child is still present")
                    finally:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        child.wait()

    def test_group_cancellation_stops_pre_main_and_post_lifecycle(self):
        self.check_native_cancellation(group=True)

    def test_directed_cancellation_stops_pre_main_and_post_lifecycle(self):
        self.check_native_cancellation(group=False)

    def test_native_exec_restores_sigpipe_instead_of_surviving(self):
        fixture = RECORDER.with_name("jj_pipe_backend.sh")
        backend = self.root / "pipe-native"
        subprocess.run(["cp", str(fixture), str(backend)], check=True)
        subprocess.run(["cmp", str(fixture), str(backend)], check=True)
        backend.chmod(0o755)
        result = self.run_wrapper("status", env={**self.env, "JJ_REAL": str(backend), "JJ_USER": ""})
        self.assertIn(result.returncode, (-signal.SIGPIPE, 128 + signal.SIGPIPE), result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual([], self.calls())

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

    def test_inherited_identity_hooks_are_best_effort_and_reset_only_human_environment(self):
        selected = self.repo()
        for command, count in (("status", 2), ("diff", 2), ("show", 2),
                               ("commit", 3), ("split", 3)):
            with self.subTest(command=command):
                self.record.unlink(missing_ok=True)
                result = self.run_wrapper(command, cwd=selected,
                                          env={**self.env, "JJ_TEST_HOOK_EXIT": "8"})
                self.assertEqual(0, result.returncode, result.stderr)
                calls = self.calls()
                self.assertEqual(count, len(calls))
                self.assertTrue(all(call["user"] == "TestAgent" for call in calls[:-1]))
                self.assertTrue(all(call["email"] == "agent@example.invalid" for call in calls[:-1]))
                self.assertIsNone(calls[-1]["user"])
                self.assertIsNone(calls[-1]["email"])

    def test_tty_diff_keeps_native_formatter_and_stdio(self):
        selected = self.repo()
        master, slave = pty.openpty()
        try:
            result = subprocess.run([str(self.wrapper), "diff"], cwd=selected,
                                    env=self.env, stdout=slave, stderr=subprocess.PIPE,
                                    text=True, timeout=5)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["diff"], self.calls()[0]["argv"])
        finally:
            os.close(master)
            os.close(slave)

    def test_invalid_real_binary_and_missing_path_backend_fail_without_execution(self):
        for real, status in ((str(self.root / "missing-native"), 1), (str(self.root), 126)):
            with self.subTest(real=real):
                result = self.run_wrapper("status", env={**self.env, "JJ_REAL": real})
                self.assertEqual(status, result.returncode, result.stderr)
                if status == 1:
                    self.assertIn("configured real jj is not executable", result.stderr)
                self.assertEqual([], self.calls())
        commands = self.root / "python-only"
        commands.mkdir()
        (commands / "python3").symlink_to(shutil.which("python3"))
        result = self.run_wrapper("status", env={**self.env, "JJ_REAL": "", "PATH": str(commands)})
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("real jj not found on PATH", result.stderr)
        self.assertEqual([], self.calls())

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

    def test_second_workspace_selectors_keep_arguments_cwd_and_proxy_failures(self):
        active = self.repo("active")
        dotfiles = self.repo("allocated-config")
        nested = active / "nested"
        nested.mkdir()
        env = {**self.env, "JJ_PROXY_REPO": str(active),
               "JJ_PROXY_ROOTS": json.dumps([str(active), str(dotfiles)])}
        cases = ((nested, ["-R", str(dotfiles), "commit", "root:skills/example", "-m", "change"]),
                 (nested, ["--repository", os.path.relpath(dotfiles, nested), "commit", "skills/example"]),
                 (dotfiles, ["-R", str(active), "commit", "root:project-file"]),
                 (dotfiles, ["status"]))
        for cwd, args in cases:
            for status in (0, 2, 125):
                with self.subTest(cwd=cwd, args=args, status=status):
                    self.record.unlink(missing_ok=True)
                    result = self.run_wrapper(*args, cwd=cwd,
                                              env={**env, "JJ_TEST_MAIN_EXIT": str(status)})
                    self.assertEqual(status, result.returncode, result.stderr)
                    self.assertEqual(["proxy"], [call["role"] for call in self.calls()])
                    self.assertEqual(args, self.calls()[0]["argv"])
                    self.assertEqual(str(cwd), self.calls()[0]["cwd"])

    def test_guest_workspace_with_host_store_reports_namespace_error_without_native_retry(self):
        linked = self.root / "linked"
        (linked / ".jj").mkdir(parents=True)
        (linked / ".jj/repo").write_text(str(ROOT / ".jj/repo"))
        subprocess.run(["cp", str(WRAPPER), str(self.wrapper)], check=True)
        subprocess.run(["cmp", str(WRAPPER), str(self.wrapper)], check=True)
        self.wrapper.write_text(self.wrapper.read_text().replace(
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
            for name in ("", "bad\nmodel", "bad\rmodel", "bad\tmodel", "bad\x1fmodel", "bad\x7fmodel", "bad\x80model", "bad\x85model", "bad\x9fmodel"):
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
                       {"modelId": "bad\nmodel"}, {"modelId": "bad\x7fmodel"},
                       {"modelId": "bad\x85model"}):
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

    @unittest.skipUnless(Path('/src') in ROOT.parents, 'wire protocol fixture requires checkout under /src')
    def test_private_split_runtime_identity_reaches_actual_client_request(self):
        target = ROOT / "target"
        target.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=target, prefix="jj-wire-")
        self.addCleanup(temporary.cleanup)
        workspace_root = Path(temporary.name)
        active = workspace_root / "active"
        active.mkdir()
        repository = workspace_root / "relocated-dotfiles"
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
                    response = json.dumps({"version": 2, "exit": 0, "stdout": "split-ok\n", "stderr": ""}).encode()
                    connection.sendall(struct.pack(">I", len(response)) + response)
            except Exception as error:
                errors.append(error)

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        subprocess.run(["cp", str(WRAPPER), str(self.wrapper)], check=True)
        subprocess.run(["cmp", str(WRAPPER), str(self.wrapper)], check=True)
        self.wrapper.write_text(self.wrapper.read_text().replace(
            "/libexec/agent-wrappers/jj-proxy-client", str(ROOT / "tools/jj-proxy/client")))
        env = {**self.env, "JJ_PROXY_REPO": str(active), "JJ_AGENT": "pi",
               "JJ_PROXY_ROOTS": json.dumps([str(active), str(repository)]),
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
        self.assertEqual(2, requests[0]["version"])
        self.assertEqual(str(repository), requests[0]["cwd"])
        self.assertEqual("mutate", requests[0]["mode"])
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
        for mode, status in (("failed", 9), ("duplicate", 125), ("relative", 125),
                             ("extra", 125), ("missing", 125),
                             ("nul-command", 125), ("nul-target", 125)):
            with self.subTest(mode=mode):
                self.record.unlink(missing_ok=True)
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
