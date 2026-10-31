from __future__ import annotations

import base64
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "codex-sandbox"
LAUNCHER = TOOL / "codex-sandbox"
LAUNCHER_FIXTURE = TOOL / "tests" / "launcher_fixture.py"
AGENT_WRAPPERS_PROFILE = TOOL / "image" / "agent-wrappers-path.sh"
DOTFILES_PROFILE = TOOL / "image" / "dotfiles-profile.sh"
SANDBOX_GITCONFIG = TOOL / "image" / "gitconfig"
SANDBOX_DOCKERFILE = TOOL / "image" / "Dockerfile"
SANDBOX_PI = TOOL / "image" / "pi"
os.environ["CODEX_SANDBOX_QUIET_NOTICES"] = "1"
try:
    NATIVE_TMUX = runpy.run_path(str(ROOT / "libexec/tmux/attachment.py"))["native_tmux"]()
except RuntimeError:
    NATIVE_TMUX = None


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o700)


def read_calls(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("\t")[1:] for line in path.read_text(encoding="utf-8").splitlines()]


class ContainerRepositoryPathTest(unittest.TestCase):
    def test_host_pi_startup_overlap_requires_the_input_barrier(self):
        blocks = runpy.run_path(str(LAUNCHER))["host_pi_blocks_startup_input"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            bundle = home / ".local/share/pi/source/packages/coding-agent/dist/bundle/cli.js"
            bundle.parent.mkdir(parents=True)
            bundle.write_text('showStatus("Startup is still in progress")')
            self.assertFalse(blocks(home))
            bundle.write_text('showStatus("Startup is still in progress; waiting for extensions")')
            self.assertTrue(blocks(home))

    def test_missing_agent_docker_access_warns_without_blocking_startup(self):
        load = runpy.run_path(str(LAUNCHER))["load_agent_docker"]
        with tempfile.TemporaryDirectory() as directory:
            access = Path(directory) / "agent-docker"
            state = SimpleNamespace(
                agent_docker_access=access,
                agent_docker_connection=access / "connection.env",
                agent_docker_key=access / "id_ed25519",
                agent_docker_known_hosts=access / "known_hosts.sandbox",
                agent_docker=None,
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                load(state)
            self.assertIsNone(state.agent_docker)
            self.assertIn("warning: nested-containers requested", stderr.getvalue())
            self.assertIn(str(access), stderr.getvalue())
            self.assertIn("tools/agent-docker/README.md", stderr.getvalue())
            self.assertIn("docker unavailable", stderr.getvalue())

    def test_detached_owner_worker_uses_log_and_null_stdin_before_bootstrap(self):
        launcher = runpy.run_path(str(LAUNCHER))
        run_agent = launcher["run_agent"]
        import host_pi_owner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            git_directory = repository / ".git"
            git_directory.mkdir(parents=True)
            subdirectory = repository / "nested"
            subdirectory.mkdir()
            state = SimpleNamespace(
                repository=repository, git_repository=repository,
                container_repository=Path("/src/repo"), home=root / "home",
                host_working_directory=subdirectory, skills_tmp=root / "skills",
                image="agent-image", codex_container="worker-container",
                codex_arguments=[], pi_model_session_id="test-session",
                handoff_origin=None,
            )
            for role, (_, destination) in launcher["STAGED_CONFIG"].items():
                source = state.skills_tmp / "config" / role
                source.parent.mkdir(parents=True, exist_ok=True)
                if destination.endswith("/agents") or role == "models":
                    source.mkdir()
                else:
                    source.touch()
            log_path = root / "owner.log"
            with log_path.open("w+") as log:
                @contextlib.contextmanager
                def workload(_image, _name, _options, _command, **stdio):
                    self.assertEqual(subprocess.DEVNULL, stdio.get("stdin"))
                    for stream in ("stdout", "stderr"):
                        descriptor = stdio[stream]
                        self.assertIsInstance(descriptor, int)
                        self.assertTrue(stat.S_ISREG(os.fstat(descriptor).st_mode))
                        self.assertEqual(os.stat(log_path), os.fstat(descriptor))
                    # Exercise the exact production handoff with a native child.
                    with subprocess.Popen([
                        sys.executable, "-c",
                        "import json, os, sys; "
                        "print(json.dumps([os.isatty(fd) for fd in range(3)])); "
                        "print('worker stderr', file=sys.stderr); "
                        "assert sys.stdin.read() == ''; sys.exit(17)",
                    ], **stdio) as worker:
                        self.assertEqual(17, worker.wait(timeout=5))
                        yield worker

                runtime = SimpleNamespace(
                    argv=mock.Mock(return_value=["admitted-engine", "fixed-channel"]),
                    environment_file=lambda _environment: contextlib.nullcontext([]),
                    inspect_image=mock.Mock(return_value="inspected-image"),
                    workload=workload,
                )
                with mock.patch.object(host_pi_owner, "OWNER_LOG_FD", log.fileno()), \
                        mock.patch.object(host_pi_owner, "HostPiOwner") as owner, \
                        mock.patch.object(host_pi_owner, "send"), \
                        mock.patch.dict(run_agent.__globals__, {
                            "HOST_PI_BOOTSTRAP": object(), "OUTER_RUNTIME": runtime,
                            "scratch_directory": lambda: root,
                            "host_pi_blocks_startup_input": lambda _home: True,
                            "run": mock.Mock(return_value=SimpleNamespace(
                                stdout=f"{git_directory}\n{git_directory}\n")),
                            "host_pi_resource_paths": lambda _state: {
                                str(repository): "/src/repo"},
                            "build_agent_command": mock.Mock(return_value=[
                                "docker", "run", "--name", "worker-container", "agent-image"]),
                        }):
                    with self.assertRaisesRegex(launcher["LauncherError"],
                                                "guest tool worker exited during startup"):
                        run_agent(state, [])
                    owner.return_value.release_frontend.assert_called_once_with()
                    owner.return_value.start.assert_called_once_with()
                    owner.return_value.worker_lost.assert_called_once_with()
                    environment = owner.call_args.args[3]
                    self.assertEqual("/src/repo", environment["CODEX_SANDBOX_GUEST_REPO"])
                    self.assertEqual("/src/repo/nested", environment["CODEX_SANDBOX_GUEST_CWD"])
                    self.assertEqual(["admitted-engine", "fixed-channel"],
                                     json.loads(environment["CODEX_SANDBOX_TOOL_COMMAND"]))
                    self.assertEqual(state.pi_tool_connector,
                                     Path(environment["CODEX_SANDBOX_TOOL_CONNECT"]))
                    self.assertEqual((TOOL / "sandbox-tool-connect-bound").read_bytes(),
                                     state.pi_tool_connector.read_bytes())
                    self.assertFalse(state.pi_tool_connector.is_relative_to(state.pi_agent_tmp))
                    runtime.argv.assert_called_once_with([
                        "exec", "--interactive", "worker-container", "node",
                        "/opt/agent-tools/bin/tool-connect.mjs",
                    ])
                log.seek(0)
                self.assertEqual({"[false, false, false]", "worker stderr"},
                                 set(log.read().splitlines()))


    def test_prepares_nested_agent_bind_mountpoints(self):
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = SimpleNamespace(pi_agent_tmp=root / "agent", skills_tmp=root / "skills")
            state.pi_agent_tmp.mkdir(mode=0o700)
            (state.skills_tmp / "config").mkdir(parents=True)
            for role, (_, destination) in launcher["STAGED_CONFIG"].items():
                source = state.skills_tmp / "config" / role
                if destination.endswith("/agents") or role == "models":
                    source.mkdir()
                else:
                    source.touch()
            launcher["prepare_agent_mountpoints"](state)
            agent = Path("/home/codex/.pi/agent")
            for role, (_, destination) in launcher["STAGED_CONFIG"].items():
                if not destination.startswith(str(agent) + "/"):
                    continue
                target = state.pi_agent_tmp / Path(destination).relative_to(agent)
                source = state.skills_tmp / "config" / role
                self.assertEqual(source.is_dir(), target.is_dir())
                self.assertTrue(target.exists())
            self.assertTrue((state.pi_agent_tmp / "pi-extensions").is_dir())
            self.assertTrue((state.pi_agent_tmp / "pi-link").is_dir())
            self.assertFalse((state.pi_agent_tmp / "extensions/codex-sidecar").exists())
            self.assertTrue((state.pi_agent_tmp / "pi-codex-subagents/runs").is_dir())

    def test_policy_opt_out_drops_host_credentials(self):
        load = runpy.run_path(str(LAUNCHER))["load_repository_policy"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = root / ".zuliprc"
            credentials.write_text("unused")
            manifest = root / "snapshot"
            manifest.write_text(json.dumps({
                "capabilities": {"host-editor": False, "zulip": False}, "commands": {},
            }))
            state = SimpleNamespace(repository=root, home=root, zuliprc=None)
            with mock.patch.dict(load.__globals__, temporary_file=lambda: manifest,
                                 helper=mock.Mock()), \
                    mock.patch.dict(os.environ, CODEX_SANDBOX_ZULIPRC=str(credentials)):
                load(state)
            self.assertIsNone(state.zuliprc)
            self.assertEqual(frozenset(), state.capabilities)

    def test_agent_image_key_tracks_sources_platform_parameters_and_actual_base(self):
        key = runpy.run_path(str(TOOL / "owned_images.py"))["agent_cache_key"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path('source')
            base = SimpleNamespace(content="sha256:" + "a" * 64,
                                   config="sha256:" + "b" * 64,
                                   rootfs="sha256:" + "c" * 64)
            previous = None
            for value in (b'', b'hello\n', b'hello\r\n', b'\xff\0binary'):
                (root / source).write_bytes(value)
                with mock.patch.dict(key.__globals__, ROOT=root, agent_sources=lambda: [source]):
                    actual = key(501, 20, "linux/arm64", base, 'a' * 40, jj_image='jj@sha256:' + '1' * 64)
                self.assertNotEqual(actual, previous)
                previous = actual
            with mock.patch.dict(key.__globals__, ROOT=root, agent_sources=lambda: [source]):
                self.assertNotEqual(actual, key(502, 20, "linux/arm64", base, 'a' * 40, jj_image='jj@sha256:' + '1' * 64))
                self.assertNotEqual(actual, key(501, 20, "linux/amd64", base, 'a' * 40, jj_image='jj@sha256:' + '1' * 64))
                changed = SimpleNamespace(**{**vars(base), "config": "sha256:" + "d" * 64})
                self.assertNotEqual(actual, key(501, 20, "linux/arm64", changed, 'a' * 40, jj_image='jj@sha256:' + '1' * 64))

    def test_failed_publication_keeps_coordination_until_cleanup(self):
        attach = runpy.run_path(str(LAUNCHER))['attach_proxies']
        lock = mock.Mock(shared=False)
        state = SimpleNamespace(proxy_lock=lock, repository=Path('/repo'),
            container_repository=Path('/src/repo'), proxy_prefix='proxy', proxy_state=Path('/state'),
            sidecar_image='image', image='agent', uid=501, gid=20,
            policy_source_present=True, manifest=Path('/manifest'), zuliprc=None,
            prepared_images=None)
        with mock.patch.dict(attach.__globals__, helper=mock.Mock(),
                finalize_proxy_session=mock.Mock(side_effect=ValueError('publication failed'))):
            with self.assertRaisesRegex(ValueError, 'publication failed'):
                attach(state)
        lock.release_coordination.assert_not_called()

    def test_only_first_session_publishes_shared_proxy_state(self):
        launcher = runpy.run_path(str(LAUNCHER))
        finalize = launcher['finalize_proxy_session']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'args'
            state = SimpleNamespace(proxy_lock=SimpleNamespace(shared=False), proxy_reused=False, repository=root,
                                    container_repository=Path('/src/repo'),
                                    proxy_state=root / 'state', manifest=root / 'manifest')
            def helper(operation, *arguments):
                output.write_text('--read-only\n')
            for status, operation in (('shared', 'agent-args'), ('idle', 'agent-args'), ('new', 'finalize')):
                with self.subTest(status=status):
                    state.proxy_lock.shared = status == 'shared'
                    state.proxy_reused = status == 'idle'
                    with mock.patch.dict(finalize.__globals__, {
                            'temporary_file': lambda: output,
                            'helper': mock.Mock(side_effect=helper)}) as scope:
                        self.assertEqual(['--read-only'], finalize(state))
                        self.assertEqual(operation, scope['helper'].call_args.args[0])

    def test_network_verification_failure_retains_captured_diagnostic(self):
        launcher = runpy.run_path(str(LAUNCHER))
        failure = subprocess.CalledProcessError(255, ['/private/client'], stderr=b'SSH session refused\n')
        runtime = mock.Mock()
        runtime.ensure_public_network.side_effect = failure
        with mock.patch.dict(launcher['ensure_network'].__globals__, {'OUTER_RUNTIME': runtime}):
            with self.assertRaisesRegex(launcher['LauncherError'],
                                        'Sandbox network setup failed .*SSH session refused') as raised:
                launcher['ensure_network']()
        self.assertNotIn('/private/client', str(raised.exception))

    def test_captured_startup_failure_is_visible(self):
        launcher = runpy.run_path(str(LAUNCHER))
        from docker_runtime import BuildError
        cases = [
            (subprocess.CalledProcessError(1, ['buildx', 'bake'], stderr='invalid Bake target\n'),
             'invalid Bake target\n'),
            (BuildError(7, ['/private/client', '--host', 'unix:///private/socket', 'buildx', 'bake']),
             'error: sandbox image build failed (exit 7); see BuildKit output above\n'),
        ]
        for failure, expected in cases:
            with self.subTest(expected=expected), \
                    mock.patch.dict(launcher['launch'].__globals__, {'image_runtime': mock.Mock(side_effect=failure)}), \
                    mock.patch('sys.stderr', new_callable=io.StringIO) as diagnostics:
                self.assertEqual(launcher['launch']([]), failure.returncode)
            self.assertEqual(expected, diagnostics.getvalue())

    def test_new_launch_clears_inherited_verification_through_cleanup(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        key = "CODEX_SANDBOX_LIMA_VERIFIED"
        state = SimpleNamespace()

        def initialize(*args):
            self.assertNotIn(key, os.environ)
            os.environ[key] = "this-launch"

        def cleanup(_state):
            self.assertEqual("this-launch", os.environ[key])

        with mock.patch.dict(os.environ, {key: "parent-launch"}), \
                mock.patch.dict(launcher["main"].__globals__, image_runtime=initialize,
                    new_state=lambda _: state, execute=lambda _: 0, cleanup=cleanup,
                    unregister_tmux_pane=lambda _: None):
            self.assertEqual(0, launcher["main"](["--mode", "rpc"]))
            self.assertEqual("parent-launch", os.environ[key])

    def test_lima_rejects_a_whole_home_container_bind_through_a_symlink(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repository = home / "src/project"
            repository.mkdir(parents=True)
            alias = home / "skills-alias"
            alias.symlink_to(home, target_is_directory=True)
            state = SimpleNamespace(home=home, repository=repository, skills_source=alias,
                metadata_roots=(), skills_tmp=repository, zuliprc=None, agent_docker=None)
            backend = mock.Mock()
            with mock.patch.dict(launcher["preflight_lima"].__globals__, OUTER_RUNTIME=backend):
                with self.assertRaisesRegex(launcher["LauncherError"], "whole home"):
                    launcher["preflight_lima"](state)
            backend.host.check_bind.assert_not_called()
            backend.host.check_binds.assert_not_called()
            backend.check_binds.assert_not_called()

    def test_lima_preflight_submits_all_mount_permissions_in_one_batch(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repository = home / "src/project"
            repository.mkdir(parents=True)
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").touch()
            state = SimpleNamespace(home=home, repository=repository, skills_source=repository,
                metadata_roots=(), skills_tmp=repository, zuliprc=None, agent_docker=None)
            backend = mock.Mock()
            with mock.patch.dict(launcher["preflight_lima"].__globals__, OUTER_RUNTIME=backend):
                launcher["preflight_lima"](state)
            backend.host.check_bind.assert_not_called()
            backend.host.check_binds.assert_not_called()
            backend.check_binds.assert_called_once()
            sources = backend.check_binds.call_args.args[0]
            self.assertIn((repository, True), sources)
            self.assertIn((repository, False), sources)
            self.assertNotIn((home / ".codex/config.toml", False), sources)
            for name in ("sessions", "npm", "git"):
                self.assertIn((home / ".pi/agent" / name, True), sources)

    def test_preserves_repository_path_beneath_home_source_root(self) -> None:
        function = runpy.run_path(str(LAUNCHER))["container_repository_path"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repository = home / "src" / "nested" / "project"
            repository.mkdir(parents=True)
            self.assertEqual(Path("/src/nested/project"), function(home, repository))

    def test_preserves_invocation_subdirectory_inside_repository(self) -> None:
        function = runpy.run_path(str(LAUNCHER))["container_working_directory_path"]
        repository = Path("/host/src/llms")
        self.assertEqual(
            Path("/src/llms/playground"),
            function(repository, Path("/src/llms"), repository / "playground"),
        )

    def test_uses_stable_fallback_outside_home_source_root(self) -> None:
        function = runpy.run_path(str(LAUNCHER))["container_repository_path"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / "src").mkdir(parents=True)
            repository = root / "project"
            repository.mkdir()
            self.assertEqual(Path("/src/repository"), function(home, repository))


class SharedProxyCleanupTest(unittest.TestCase):
    def repository(self, directory):
        root = Path(directory) / "repo"
        subprocess.run(["jj", "git", "init", str(root)], cwd=directory,
                       check=True, stdout=subprocess.DEVNULL)
        return root

    def test_launcher_removes_shared_services_after_last_attachment(self):
        launcher = runpy.run_path(str(LAUNCHER))
        proxies = launcher["proxy_module"]()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            runtime = proxies.runtime_directory(root)
            recovery = {"runtime": {"provider": "container"}, "proxies": []}
            metadata = runtime / "session.json"
            metadata.write_text(json.dumps({"version": 2, "state": recovery}))
            first = launcher["new_state"]([])
            first.repository = root
            first.proxy_lock = launcher["SessionLock"](runtime)
            first.proxy_lock.release_coordination()
            second = launcher["new_state"]([])
            second.repository = root
            second.proxy_lock = launcher["SessionLock"](runtime)
            with mock.patch.object(proxies, "stop_state") as stop, \
                    mock.patch.dict(launcher["cleanup"].__globals__, defer_proxy_cleanup=mock.Mock(return_value=False)):
                self.assertTrue(launcher["cleanup"](first))
                stop.assert_not_called()
                self.assertTrue(metadata.exists())
                self.assertTrue(launcher["cleanup"](second))
                stop.assert_called_once_with(recovery)
                self.assertFalse(metadata.exists())
                # Cleanup is idempotent even when invoked again by finalization.
                self.assertTrue(launcher["cleanup"](second))
                self.assertEqual(1, stop.call_count)

    def test_successful_final_attachment_retains_shared_services_for_idle_reuse(self):
        launcher = runpy.run_path(str(LAUNCHER))
        proxies = launcher["proxy_module"]()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            runtime = proxies.runtime_directory(root)
            metadata = runtime / "session.json"
            metadata.write_text(json.dumps({"version": 2, "state": {
                "runtime": {"provider": "container"}, "proxies": [],
            }}))
            state = launcher["new_state"]([])
            state.repository = root
            state.completed_successfully = True
            state.proxy_lock = launcher["SessionLock"](runtime)
            state.proxy_lock.release_coordination()
            defer = mock.Mock(return_value=True)
            with mock.patch.object(proxies, "stop_state") as stop, \
                    mock.patch.dict(launcher["cleanup"].__globals__, defer_proxy_cleanup=defer):
                self.assertTrue(launcher["cleanup"](state))
            defer.assert_called_once_with(state)
            stop.assert_not_called()
            self.assertTrue(metadata.exists())

    def test_idle_cleanup_detaches_only_after_success(self):
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            state = SimpleNamespace(completed_successfully=True, repository=Path("/repo"))
            module = SimpleNamespace(
                runtime_directory=lambda _repo: runtime,
                write_atomic=lambda path, value: path.write_text(value),
            )
            with mock.patch.dict(launcher["defer_proxy_cleanup"].__globals__,
                                 proxy_module=lambda: module), \
                    mock.patch.object(launcher["defer_proxy_cleanup"].__globals__["secrets"],
                                      "token_hex", return_value="lease"), \
                    mock.patch("subprocess.Popen") as start:
                self.assertTrue(launcher["defer_proxy_cleanup"](state))
            command = start.call_args.args[0]
            self.assertEqual(["idle-cleanup", "--repo", "/repo", "--delay", "300.0",
                              "--lease", "lease"], command[1:])
            self.assertEqual("lease", (runtime / "idle-cleanup.lease").read_text())
            self.assertTrue(start.call_args.kwargs["start_new_session"])
            state.completed_successfully = False
            with mock.patch("subprocess.Popen") as start:
                self.assertFalse(launcher["defer_proxy_cleanup"](state))
            start.assert_not_called()

    def test_launcher_retains_unpublished_recovery_on_removal_failure(self):
        launcher = runpy.run_path(str(LAUNCHER))
        proxies = launcher["proxy_module"]()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, HOME=directory):
            root = self.repository(directory)
            runtime = proxies.runtime_directory(root)
            state = launcher["new_state"]([])
            state.repository = root
            state.proxy_lock = launcher["SessionLock"](runtime)
            state.proxy_state = root / "unpublished.json"
            recovery = {"runtime": {"provider": "container"}, "proxies": []}
            state.proxy_state.write_text(json.dumps(recovery))
            with mock.patch.object(proxies, "stop_state", side_effect=proxies.ConfigError("busy")):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertFalse(launcher["cleanup"](state))
            self.assertIn("Shared proxy cleanup failed", stderr.getvalue())
            metadata = runtime / "session.json"
            self.assertEqual(recovery, proxies.session_state(json.loads(metadata.read_text())))
            self.assertTrue(state.proxy_state.exists())
            with mock.patch.object(proxies, "stop_state") as stop:
                self.assertEqual(0, proxies.reset_main(SimpleNamespace(repo=str(root))))
            stop.assert_called_once_with(recovery)
            self.assertFalse(metadata.exists())


class ProxyHelperTest(unittest.TestCase):
    def test_short_calls_do_not_spawn_an_interpreter_and_preserve_failure(self) -> None:
        helper = runpy.run_path(str(LAUNCHER))["helper"]
        entrypoint = mock.Mock(return_value=0)
        with mock.patch.dict(helper.__globals__, proxy_module=lambda: SimpleNamespace(main=entrypoint)), \
                mock.patch("subprocess.run", side_effect=AssertionError("unexpected process")):
            self.assertEqual(0, helper("snapshot", "--repo", "example").returncode)
            entrypoint.assert_called_once_with(["snapshot", "--repo", "example"],
                                               runtime=helper.__globals__["OUTER_RUNTIME"])
            entrypoint.return_value = 1
            with self.assertRaises(subprocess.CalledProcessError):
                helper("snapshot", "--repo", "example")
            self.assertEqual(1, helper("snapshot", "--repo", "example", check=False).returncode)


class ContainerTimingTest(unittest.TestCase):
    def test_daemon_timestamps_keep_host_clock_out_of_durations(self) -> None:
        report = runpy.run_path(str(LAUNCHER))["report_container_timing"]
        timestamps = "|".join(json.dumps(value) for value in (
            "2026-09-06T01:00:00.123456789-04:00",
            "2026-09-06T01:00:00.373456789-04:00",
            "2026-09-06T01:00:07.873456789-04:00",
        ))
        with mock.patch("subprocess.run", return_value=SimpleNamespace(stdout=timestamps)), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            report(SimpleNamespace(codex_container="measurement"))
        self.assertIn("creation to start=0.25s, start to exit=7.50s", output.getvalue())

    def test_failed_inspection_does_not_prevent_cleanup(self) -> None:
        report = runpy.run_path(str(LAUNCHER))["report_container_timing"]
        for error in (OSError("missing CLI"), subprocess.TimeoutExpired("docker", 5),
                      subprocess.CalledProcessError(1, "docker")):
            with self.subTest(error=error), mock.patch("subprocess.run", side_effect=error), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as output:
                report(SimpleNamespace(codex_container="measurement"))
                self.assertIn("timing: unavailable", output.getvalue())

    def test_missing_or_invalid_timestamps_are_unavailable(self) -> None:
        report = runpy.run_path(str(LAUNCHER))["report_container_timing"]
        for timestamps in ("", "null|null|null", '"bad"|"bad"|"bad"',
                           '"2026-09-06T00:00:00Z"|"0001-01-01T00:00:00Z"|"0001-01-01T00:00:00Z"'):
            with self.subTest(timestamps=timestamps), \
                    mock.patch("subprocess.run", return_value=SimpleNamespace(stdout=timestamps)), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as output:
                report(SimpleNamespace(codex_container="measurement"))
                self.assertIn("timing: unavailable", output.getvalue())


class HostPiWrapperTest(unittest.TestCase):
    def test_tool_worker_allows_only_isolated_information_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fake_pi = TOOL / "tests/fixtures/fake-pi-information.sh"
            wrapper = home / "pi"
            source = SANDBOX_PI.read_text(encoding="utf-8")
            self.assertEqual(2, source.count("/opt/agent-pi/standalone/pi"))
            wrapper.write_text(source.replace("/opt/agent-pi/standalone/pi", str(fake_pi)),
                               encoding="utf-8")
            caller_agent = home / "caller-agent"
            caller_agent.mkdir()
            caller_cache = home / "caller-node-cache"
            caller_xdg = home / "caller-xdg-cache"
            empty_bin = home / "empty-bin"
            empty_bin.mkdir()
            missing_tmp = home / "missing-tmp"
            environment = {
                "CODEX_SANDBOX_TOOL_WORKER": "1",
                "HOME": str(home),
                "NODE_COMPILE_CACHE": str(caller_cache),
                "PATH": str(empty_bin),
                "PI_CODING_AGENT_DIR": str(caller_agent),
                "PI_PACKAGE_DIR": str(home / "caller-package"),
                "TMPDIR": str(missing_tmp),
                "XDG_CACHE_HOME": str(caller_xdg),
            }
            bad = subprocess.run([str(fake_pi), "--offline", "--version"],
                                 env=environment, text=True, capture_output=True)
            self.assertEqual(89, bad.returncode)
            for argument in ("--help", "--version"):
                with self.subTest(argument=argument):
                    result = subprocess.run(
                        ["/bin/sh", str(wrapper), argument],
                        env=environment,
                        text=True, capture_output=True,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    if argument == "--help":
                        self.assertIn("Usage:", result.stdout)
                    else:
                        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+$")
                    self.assertFalse((home / ".pi").exists())
                    self.assertFalse(caller_cache.exists())
                    self.assertFalse(caller_xdg.exists())
                    self.assertFalse(missing_tmp.exists())

            result = subprocess.run(
                ["/bin/sh", str(wrapper), "--list-models"],
                env=environment,
                text=True, capture_output=True,
            )
            self.assertEqual(64, result.returncode)
            self.assertEqual(
                "pi is unavailable in sandbox tool-worker containers\n",
                result.stderr,
            )
            self.assertFalse((home / ".pi").exists())

    def test_live_tool_worker_identity_cannot_be_overridden(self) -> None:
        try:
            pid_one = Path("/proc/1/cmdline").read_bytes().split(b"\0")
        except OSError:
            self.skipTest("requires Linux procfs")
        if b"/opt/agent-tools/bin/tool-worker.mjs" not in pid_one:
            self.skipTest("requires a live sandbox tool-worker container")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for marker in (None, "0"):
                with self.subTest(marker=marker):
                    environment = {"HOME": str(home)}
                    if marker is not None:
                        environment["CODEX_SANDBOX_TOOL_WORKER"] = marker
                    result = subprocess.run(
                        ["/bin/sh", str(SANDBOX_PI), "--list-models"],
                        env=environment, text=True, capture_output=True,
                    )
                    self.assertEqual(64, result.returncode)
                    self.assertEqual(
                        "pi is unavailable in sandbox tool-worker containers\n",
                        result.stderr,
                    )
                    self.assertFalse((home / ".pi").exists())

    def test_subagent_extensions_come_from_host_wrapper(self) -> None:
        config = json.loads((ROOT / "config/pi-agent/pi-codex-subagents/config.json").read_text())
        self.assertEqual([], config.get("defaults", {}).get("extensions", []))

    def test_child_keeps_guest_tools_and_drops_guest_credential_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            cli = home / ".local/share/pi/node/node_modules/.bin/pi"
            cli.parent.mkdir(parents=True)
            cli.write_text("#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
            cli.chmod(0o755)
            sidecar = home / ".pi/agent/pi-extensions/codex-sidecar.ts"
            installed_index = home / ".pi/agent/pi-extensions/index.ts"
            result = subprocess.run(
                [str(TOOL / "sandbox-host-pi"), "--mode", "rpc", "--no-extensions",
                 "--extension", str(sidecar), "--extension", str(installed_index),
                 "--session", "child.jsonl"],
                env={**os.environ, "HOME": str(home)}, capture_output=True, text=True, check=True,
            )
            args = json.loads(result.stdout)
            self.assertEqual("--extension", args[0])
            self.assertEqual(str(ROOT / "config/pi-agent/pi-extensions/index.ts"), args[1])
            self.assertEqual("--extension", args[2])
            self.assertEqual(str(ROOT / "config/pi-agent/pi-extensions/guest-tools.ts"), args[3])
            self.assertEqual(["--mode", "rpc", "--no-extensions", "--session", "child.jsonl"],
                             args[4:])

    def test_wrapper_preserves_guest_paths_in_startup_prompt(self) -> None:
        if shutil.which("bun") is None:
            self.skipTest("requires Bun")
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            host_repository = home / "src/personal/lapwing/stint"
            host_repository.mkdir(parents=True)
            cli = home / ".local/share/pi/node/node_modules/.bin/pi"
            cli.parent.mkdir(parents=True)
            cli.write_text(
                "#!/usr/bin/env bun\n"
                "const { rewritePiResourcePaths } = await import(process.env.FIXTURE_CORE);\n"
                "const host = process.env.FIXTURE_HOST;\n"
                "const home = process.env.FIXTURE_HOME;\n"
                "const piPackage = process.env.FIXTURE_PI_PACKAGE;\n"
                "const prompt = [\n"
                "  `Project config: ${host}/config/agents/breq.md`,\n"
                "  `Shared skill: ${home}/.agents/skills/spec-review/SKILL.md`,\n"
                "  `Package skill: ${home}/.pi/agent/pi-link/skills/pi-link-tools/SKILL.md`,\n"
                "  `Agent instructions: <project_instructions path=\\\"${home}/.pi/agent/AGENTS.md\\\">`,\n"
                "  `Pi examples: ${piPackage}/examples`,\n"
                "  `Guest package: /opt/agent-pi/src/packages/coding-agent/README.md`,\n"
                "  `Guest checkout: /src/dotfiles/AGENTS.md`,\n"
                "  `Sibling location: ${host}-old/.agents/skills/spec-review/SKILL.md`,\n"
                "].join(\"\\n\");\n"
                "console.log(JSON.stringify({args: process.argv.slice(2),\n"
                "  prompt: rewritePiResourcePaths(prompt, JSON.parse(process.env.CODEX_SANDBOX_PI_RESOURCE_PATHS))}));\n",
                encoding="utf-8",
            )
            cli.chmod(0o700)
            host_pi_package = home / ".local/share/pi/source/packages/coding-agent"
            agents_source = home / "src/dotfiles/config/pi-agent/AGENTS.md"
            agents_source.parent.mkdir(parents=True)
            agents_source.write_text("Host instructions.\n", encoding="utf-8")
            resource_paths_function = launcher["host_pi_resource_paths"]
            with mock.patch.dict(resource_paths_function.__globals__, {
                "installed_config_source": lambda _target: agents_source,
            }):
                resource_paths = resource_paths_function(SimpleNamespace(
                    home=home,
                    host_pi_package=host_pi_package,
                    repository=host_repository,
                    container_repository=Path("/src/personal/lapwing/stint"),
                ))
            result = subprocess.run(
                [str(TOOL / "sandbox-host-pi"), "--mode", "rpc"],
                env={**os.environ, "HOME": str(home),
                     "CODEX_SANDBOX_PI_RESOURCE_PATHS": json.dumps(resource_paths),
                     "FIXTURE_CORE": str(ROOT / "config/pi-agent/pi-extensions/guest-tools-core.ts"),
                     "FIXTURE_HOME": str(home),
                     "FIXTURE_HOST": str(host_repository),
                     "FIXTURE_PI_PACKAGE": str(host_pi_package)},
                capture_output=True, text=True, check=True,
            )
            output = json.loads(result.stdout)
            self.assertLess(
                output["args"].index(str(ROOT / "config/pi-agent/pi-extensions/index.ts")),
                output["args"].index(str(ROOT / "config/pi-agent/pi-extensions/guest-tools.ts")),
            )
            self.assertEqual(
                [
                    "Project config: /src/personal/lapwing/stint/config/agents/breq.md",
                    "Shared skill: /home/codex/.agents/skills/spec-review/SKILL.md",
                    "Package skill: /home/codex/.pi/agent/pi-link/skills/pi-link-tools/SKILL.md",
                    "Agent instructions: <project_instructions path=\"/src/dotfiles/config/pi-agent/AGENTS.md\">",
                    "Pi examples: /opt/agent-pi/src/packages/coding-agent/examples",
                    "Guest package: /opt/agent-pi/src/packages/coding-agent/README.md",
                    "Guest checkout: /src/dotfiles/AGENTS.md",
                    "Sibling location: /src/personal/lapwing/stint-old/.agents/skills/spec-review/SKILL.md",
                ],
                output["prompt"].splitlines(),
            )


class RepositoryPreflightTest(unittest.TestCase):
    def test_non_repository_rejects_before_runtime_or_initialization(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        runtime = mock.Mock(side_effect=AssertionError("runtime accessed before repository check"))
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory), \
                mock.patch.dict(launcher["launch"].__globals__, image_runtime=runtime), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as diagnostics:
            self.assertEqual(1, launcher["launch"](["--help"]))
            self.assertIn("existing Git repository", diagnostics.getvalue())
            self.assertEqual([], list(Path(directory).iterdir()))
        runtime.assert_not_called()

    def test_real_git_subdirectory_adds_jj_without_creating_nested_git(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repository = home / "src" / "project"
            repository.mkdir(parents=True)
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            nested = repository / "nested"
            nested.mkdir()
            state = SimpleNamespace(home=home)
            with contextlib.chdir(nested), mock.patch.dict(
                launcher["validate_repository"].__globals__, DOTFILES=repository,
            ):
                launcher["validate_repository"](state)
            self.assertEqual(1, len(state.workspaces))
            state.workspaces_file.unlink()
            self.assertEqual(repository, state.repository)
            self.assertEqual(repository / ".git", state.git_mount_source)
            self.assertTrue((repository / ".jj").is_dir())
            self.assertEqual([], list(nested.iterdir()))


class DirectoryHandoffTest(unittest.TestCase):
    def test_cross_directory_session_id_forks_before_pi_starts(self) -> None:
        prepare = runpy.run_path(str(LAUNCHER))["prepare_host_session"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source_directory = home / "old"
            destination = home / "new"
            source_directory.mkdir()
            destination.mkdir()
            sessions = home / ".pi/agent/sessions/old"
            sessions.mkdir(parents=True)
            session = sessions / "2026-09-17_session-one.jsonl"
            session.write_text(json.dumps({"type": "session", "id": "session-one",
                                           "cwd": str(source_directory)}) + "\n")
            state = SimpleNamespace(codex_arguments=["--session-id", "session-one"],
                                    home=home, host_working_directory=destination)
            prepare(state)
            self.assertEqual(["--fork", str(session.resolve()), "--session-id"],
                             state.codex_arguments[:3])
            uuid.UUID(state.codex_arguments[3])

            state.codex_arguments = ["--session", "session-one"]
            prepare(state)
            self.assertEqual(["--fork", str(session.resolve()), "--session-id"],
                             state.codex_arguments[:3])

            state.codex_arguments = ["--session", str(session)]
            prepare(state)
            self.assertEqual(["--fork", str(session.resolve()), "--session-id"],
                             state.codex_arguments[:3])

            state.host_working_directory = source_directory
            state.codex_arguments = ["--session-id", "session-one"]
            prepare(state)
            self.assertEqual(["--session-id", "session-one"], state.codex_arguments)

            custom_sessions = home / "custom-sessions"
            custom_sessions.mkdir()
            custom_session = custom_sessions / "2026-09-17_session-two.jsonl"
            custom_session.write_text(json.dumps({"type": "session", "id": "session-two",
                                                  "cwd": str(source_directory)}) + "\n")
            state.host_working_directory = destination
            state.codex_arguments = ["--session-id", "session-two"]
            with mock.patch.dict(os.environ, {"PI_CODING_AGENT_SESSION_DIR": str(custom_sessions)}):
                prepare(state)
            self.assertEqual(["--fork", str(custom_session.resolve()), "--session-id"],
                             state.codex_arguments[:3])

            state.codex_arguments = ["--session-dir", str(custom_sessions),
                                     "--session-id", "session-two"]
            prepare(state)
            self.assertEqual(["--session-dir", str(custom_sessions), "--fork",
                              str(custom_session.resolve()), "--session-id"],
                             state.codex_arguments[:5])

    def test_prepare_cd_builds_the_destination_base_without_starting_or_releasing_sessions(self) -> None:
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                destination = root / "destination"
                subprocess.run([os.environ.get("DOTFILES_TEST_JJ_REAL", "jj"), "git", "init", "--colocate",
                                str(destination)], cwd=root, check=True, capture_output=True)
                policy = destination / ".agents/sandbox"
                policy.mkdir(parents=True)
                (policy / "proxy-commands.json").write_text(json.dumps({
                    "version": 2, "commands": {},
                    "images": {"base": "destination-base", "resolver": {"kind": "command", "argv": [
                        sys.executable, str(TOOL / "tests/fixtures/launch-resolver.py")]}}}))
                launcher = runpy.run_path(str(LAUNCHER))
                launch = launcher["launch"]
                module = launcher["proxy_module"]()
                manifest = root / "snapshot.json"
                module.snapshot_main(SimpleNamespace(repo=str(destination), output=str(manifest), jj_image_command=None))
                snapshot = manifest.read_text()
                state = SimpleNamespace(repository=destination, host_working_directory=destination,
                                        manifest=None, capabilities=frozenset(), uid=501, gid=20)
                runtime = mock.Mock(spec=launcher["ContainerRuntime"], provider="container")
                runtime.build_platform.return_value = "linux/amd64"
                runtime.builder_environment.side_effect = lambda: dict(os.environ)
                runtime.verify_builder_image.side_effect = lambda image: SimpleNamespace(reference=image)
                compose = mock.Mock(return_value="agent-image")
                if failure:
                    compose.side_effect = ValueError("Cannot find module './identity.js'")
                def load_policy(value):
                    value.manifest = manifest
                    manifest.write_text(snapshot)
                forbidden = {name: mock.Mock(side_effect=AssertionError(name + " must not run during preparation"))
                             for name in ("acquire_lock", "run_agent", "cleanup", "unregister_tmux_pane",
                                          "ensure_network", "attach_proxies", "register_tmux_pane")}
                replacements = {**forbidden, "image_runtime": lambda: runtime,
                                "new_state": lambda _args: state,
                                "validate_repository": mock.Mock(),
                                "load_repository_policy": load_policy, "resolve_agent": compose}
                request = root / "request.json"
                output = io.StringIO()
                errors = io.StringIO()
                previous_cwd = Path.cwd()
                try:
                    with mock.patch.dict(launch.__globals__, replacements), mock.patch.dict(os.environ, {
                        "LAUNCH_RESOLVER_REQUEST": str(request),
                        "LAUNCH_RESOLVER_IMAGES": json.dumps({"destination-base": "sha256:" + "1" * 64}),
                    }), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        self.assertEqual(int(failure), launch(["prepare-cd", str(destination)]))
                finally:
                    os.chdir(previous_cwd)
                replacements["validate_repository"].assert_called_once_with(state, initialize_missing=False)
                compose.assert_called_once_with(runtime, 501, 20, "sha256:" + "1" * 64)
                self.assertFalse(manifest.exists(), "preparation must remove its private policy snapshot")
                for function in forbidden.values():
                    function.assert_not_called()
                if failure:
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn("Cannot find module './identity.js'", errors.getvalue())
                else:
                    self.assertEqual(json.loads(output.getvalue()), {
                        "destination": str(destination), "repository": str(destination)})
                self.assertEqual(json.loads(request.read_text())["images"], ["destination-base"])

    def test_prepare_cd_uses_the_existing_legacy_base_builder_and_cleans_on_failure(self) -> None:
        prepare = runpy.run_path(str(LAUNCHER))["prepare_cd_images"]
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            builder = repository / ".agents/sandbox/base-image"
            builder.parent.mkdir(parents=True, exist_ok=True)
            write_executable(builder, "#!/bin/sh\nprintf 'legacy-base\\n'\n")
            manifest = repository / "manifest.json"
            def load_policy(state):
                state.manifest = manifest
                manifest.write_text(json.dumps({"commands": {}}))
            state = SimpleNamespace(repository=repository, manifest=None, capabilities=frozenset(), uid=501, gid=20)
            compose = mock.Mock(side_effect=ValueError("build failed"))
            runtime = SimpleNamespace(provider="container")
            with mock.patch.dict(prepare.__globals__, {
                "OUTER_RUNTIME": runtime,
                "load_repository_policy": load_policy,
                "resolve_agent": compose,
            }):
                with self.assertRaisesRegex(ValueError, "build failed"):
                    prepare(state)
            compose.assert_called_once_with(runtime, 501, 20, "legacy-base")
            self.assertFalse(manifest.exists())

    def test_prepare_cd_rejects_a_failed_legacy_proxy_image_build(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        prepare = launcher["prepare_cd_images"]
        module = launcher["proxy_module"]()
        runtime = SimpleNamespace(provider="lima")
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            manifest = repository / "manifest.json"
            def load_policy(state):
                state.manifest = manifest
                manifest.write_text(json.dumps({"commands": {"broken": {
                    "image-command": ["/bin/false"], "argv": ["proxy", "serve"],
                    "workdir": ".", "network": False, "mounts": [],
                }}}))
            state = SimpleNamespace(repository=repository, manifest=None, capabilities=frozenset())
            model = mock.Mock(return_value="agent-image")
            with mock.patch.dict(prepare.__globals__, {
                "OUTER_RUNTIME": runtime, "load_repository_policy": load_policy,
                "resolve_model_image": model, "proxy_module": lambda: module,
            }), mock.patch.object(module, "OUTER_RUNTIME", runtime):
                with self.assertRaisesRegex(launcher["LauncherError"], "image-command for broken"):
                    prepare(state)
            model.assert_called_once_with(state)
            self.assertFalse(manifest.exists())

    def test_validation_does_not_initialize_a_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for operation in ("validate-cd", "prepare-cd"):
                with self.subTest(operation=operation):
                    result = subprocess.run(
                        [str(LAUNCHER), operation, directory], capture_output=True, text=True,
                    )
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse((Path(directory) / ".jj").exists())

    def test_prepare_cd_does_not_detach_a_new_owner(self) -> None:
        main = runpy.run_path(str(LAUNCHER))["main"]
        launch = mock.Mock(return_value=17)
        with mock.patch.dict(main.__globals__, launch=launch), mock.patch(
                "host_pi_owner.detached_frontend", side_effect=AssertionError("preparation must not detach")):
            self.assertEqual(17, main(["prepare-cd", "/destination"]))
        launch.assert_called_once_with(["prepare-cd", "/destination"])

    def test_successful_handoff_cleans_before_starting_fork(self) -> None:
        launch = runpy.run_path(str(LAUNCHER))["launch"]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            session = destination / "source.jsonl"
            session.write_text("session")
            states = [SimpleNamespace(host_working_directory=ROOT, codex_arguments=[], joining_workers=False),
                      SimpleNamespace(host_working_directory=destination, joining_workers=False)]
            events = []

            def new_state(arguments):
                events.append(("new", arguments))
                return states.pop(0)

            replacements = {
                "image_runtime": lambda: None,
                "new_state": new_state,
                "execute": lambda state: events.append(("execute", state.host_working_directory)) or
                           (0 if state.host_working_directory == ROOT else 19),
                "read_cd_request": lambda _state: (destination, session),
                "cleanup": lambda state: events.append(("cleanup", state.host_working_directory)) or True,
                "unregister_tmux_pane": lambda state: events.append(("unregister", state.host_working_directory)),
            }
            with mock.patch.dict(launch.__globals__, replacements), \
                    mock.patch("os.chdir") as change_directory:
                self.assertEqual(19, launch([]))
            self.assertEqual(("cleanup", ROOT), events[2])
            self.assertEqual("new", events[4][0])
            self.assertEqual(["--fork", str(session), "--session-id"], events[4][1][:3])
            uuid.UUID(events[4][1][3])
            change_directory.assert_called_once_with(destination)

    def test_empty_session_handoff_starts_fresh_in_destination(self) -> None:
        launch = runpy.run_path(str(LAUNCHER))["launch"]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            states = [SimpleNamespace(host_working_directory=ROOT, codex_arguments=[
                "--session-dir", "sessions"], joining_workers=False),
                      SimpleNamespace(host_working_directory=destination, joining_workers=False)]
            arguments = []

            def new_state(value):
                arguments.append(value)
                return states.pop(0)

            with mock.patch.dict(launch.__globals__, {
                "image_runtime": lambda: None,
                "new_state": new_state,
                "execute": lambda state: 0 if state.host_working_directory == ROOT else 19,
                "read_cd_request": lambda _state: (destination, None),
                "cleanup": lambda _state: True,
                "unregister_tmux_pane": lambda _state: None,
            }), mock.patch("os.chdir") as change_directory:
                self.assertEqual(19, launch([]))
            self.assertEqual([], arguments[0])
            self.assertEqual(["--session-dir", str(ROOT / "sessions"), "--session-id"],
                             arguments[1][:3])
            uuid.UUID(arguments[1][3])
            change_directory.assert_called_once_with(destination)

    def test_empty_session_request_has_no_source_file(self) -> None:
        read_request = runpy.run_path(str(LAUNCHER))["read_cd_request"]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            request = destination / "request.json"
            request.write_text(json.dumps({"destination": str(destination), "session": None}))
            self.assertEqual((destination.resolve(), None),
                             read_request(SimpleNamespace(cd_request=request)))

    def test_failed_cleanup_stops_handoff(self) -> None:
        launch = runpy.run_path(str(LAUNCHER))["launch"]
        state = SimpleNamespace(host_working_directory=ROOT, joining_workers=False)
        new_state = mock.Mock(return_value=state)
        with mock.patch.dict(launch.__globals__, {
            "image_runtime": lambda: None,
            "new_state": new_state,
            "execute": lambda _state: 0,
            "read_cd_request": lambda _state: (ROOT, ROOT / "source.jsonl"),
            "cleanup": lambda _state: False,
            "unregister_tmux_pane": lambda _state: None,
        }), mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            self.assertEqual(1, launch([]))
        new_state.assert_called_once()
        self.assertIn("cleanup failed", output.getvalue())


class BackgroundRelayTest(unittest.TestCase):
    def test_command_policy_resolves_base_and_project_consumers_before_startup(self):
        # Native raw declaration -> normalized snapshot -> protocol -> agent composition.
        for provider in ("container", "lima", "lima-docker"):
            for targets in ((), ("project-base",), ("bug-image", "project-base")):
                with self.subTest(provider=provider, targets=targets), tempfile.TemporaryDirectory() as directory:
                    launcher = runpy.run_path(str(LAUNCHER))
                    execute = launcher["execute"]
                    repository = Path(directory)
                    sandbox = repository / ".agents/sandbox"
                    sandbox.mkdir(parents=True)
                    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
                    names = {"project-base", *targets}
                    results = {name: "sha256:" + str(index + 1) * 64
                               for index, name in enumerate(sorted(names))}
                    commands = {f"proxy-{index}": {"image": target, "argv": ["proxy", "serve"],
                                "workdir": ".", "network": False, "mounts": []}
                                for index, target in enumerate(targets)}
                    (sandbox / "proxy-commands.json").write_text(json.dumps({
                        "version": 2, "capabilities": {"zulip": False}, "commands": commands,
                        "images": {"base": "project-base", "resolver": {"kind": "command", "argv": [
                            sys.executable, str(TOOL / "tests/fixtures/launch-resolver.py")]}}}))
                    module = launcher["proxy_module"]()
                    snapshot = repository / "snapshot.json"
                    module.snapshot_main(SimpleNamespace(repo=str(repository), output=str(snapshot),
                                                         jj_image_command=None))
                    state = SimpleNamespace(repository=repository, manifest=snapshot, uid=501, gid=20,
                                            capabilities=frozenset(), deferred_signal=None)
                    from sandbox_runtime import ContainerRuntime, VMRuntime
                    from docker_runtime import Docker
                    runtime_type = {"container": ContainerRuntime, "lima": VMRuntime, "lima-docker": Docker}[provider]
                    runtime = mock.Mock(spec=runtime_type, provider=provider)
                    runtime.build_platform.return_value = "linux/amd64"
                    runtime.builder_environment.side_effect = lambda: dict(os.environ)
                    runtime.verify_builder_image.side_effect = lambda image: SimpleNamespace(reference=image)
                    if provider == "lima-docker":
                        runtime.run_builders.return_value = {}
                        runtime.bake.side_effect = lambda _repo, targets: {} if not targets else self.fail("Bake fallback")
                    network = mock.Mock(return_value=[])
                    agent = mock.Mock(return_value=0)
                    compose = mock.Mock(return_value="agent-image")
                    replacements = {name: mock.Mock(return_value=[]) for name in (
                        "validate_repository", "recover_relays", "load_repository_policy", "stage_skills",
                        "register_tmux_pane", "prepare_gateway", "attach_proxies", "preflight_lima", "boot_credential")}
                    replacements.update(OUTER_RUNTIME=runtime, ensure_network=network, run_agent=agent,
                                        resolve_agent=compose,
                                        temporary_file=lambda: repository / "prepared-images.json",
                                        acquire_lock=lambda value: setattr(value, "proxy_lock", SimpleNamespace(shared=False)))
                    receipt = repository / "request.json"
                    environment = {"LAUNCH_RESOLVER_REQUEST": str(receipt),
                                   "LAUNCH_RESOLVER_IMAGES": json.dumps(results)}
                    with mock.patch.dict(execute.__globals__, replacements), mock.patch.dict(os.environ, environment):
                        self.assertEqual(0, execute(state))
                        compose.assert_called_once_with(runtime, 501, 20, results["project-base"])
                        requests = [json.loads(line) for line in receipt.read_text().splitlines()]
                        self.assertEqual(1, len(requests))
                        self.assertEqual({"version": 1, "operation": "resolve", "images": sorted(names),
                                          "engine": {"provider": provider, "platform": "linux/amd64"}}, requests[0])
                        self.assertEqual({name: results[command["image"]] for name, command in commands.items()},
                                         json.loads(state.prepared_images.read_text()))
                        self.assertEqual(len(names), runtime.verify_builder_image.call_count)
                        for invalid in ({}, {**results, "unexpected": "sha256:" + "9" * 64}):
                            network.reset_mock(); agent.reset_mock(); compose.reset_mock()
                            runtime.verify_builder_image.reset_mock()
                            with mock.patch.dict(os.environ, LAUNCH_RESOLVER_IMAGES=json.dumps(invalid)):
                                with self.assertRaisesRegex(ValueError, "exactly match"):
                                    execute(state)
                            network.assert_not_called(); agent.assert_not_called(); compose.assert_not_called()
                            runtime.verify_builder_image.assert_not_called()

    def test_malformed_new_policy_precedes_relay_and_image_effects(self):
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        state = SimpleNamespace(repository=Path("/unused"))
        effects = {name: mock.Mock(side_effect=AssertionError(name + " before rejection")) for name in (
            "recover_relays", "stage_skills", "prepare_launch_images", "start_keychain", "ensure_network", "run_agent")}
        with mock.patch.dict(execute.__globals__, effects | {
            "validate_repository": mock.Mock(),
            "acquire_lock": lambda value: setattr(value, "proxy_lock", SimpleNamespace(shared=False)),
            "load_repository_policy": mock.Mock(side_effect=ValueError("rejected raw policy")),
        }):
            with self.assertRaisesRegex(ValueError, "rejected raw policy"):
                execute(state)
        for effect in effects.values():
            effect.assert_not_called()

    def test_selects_guest_worker(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            state = SimpleNamespace(repository=Path(directory), agent_docker={}, uid=501, gid=20,
                                    codex_arguments=["--session-id", "test-session"],
                                    deferred_signal=None)
            replacements = {
                name: mock.Mock(return_value=[])
                for name in ("validate_repository", "register_tmux_pane", "ensure_network",
                             "attach_proxies", "prepare_gateway", "stage_skills", "start_keychain",
                             "prepare_host_pi_resources")
            }
            replacements["acquire_lock"] = mock.Mock(side_effect=lambda value: setattr(
                value, "proxy_lock", SimpleNamespace(shared=False)))
            replacements["load_repository_policy"] = mock.Mock()
            replacements.update(
                prepare_host_session=mock.Mock(),
                resolve_agent=mock.Mock(return_value="image"),
                resolve_sidecar_image=mock.Mock(return_value="sidecar"),
                run=mock.Mock(return_value=SimpleNamespace(stdout="Darwin")),
                run_agent=lambda _state, arguments: (calls.append(arguments) or 0),
            )
            with mock.patch.dict(execute.__globals__, replacements):
                self.assertEqual(0, execute(state))
        self.assertEqual(1, len(calls))
        self.assertEqual(["bun", "/opt/agent-tools/bin/tool-worker.mjs"], calls[0][-2:])

    def test_fresh_session_reports_image_and_proxy_preparation(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        state = SimpleNamespace(repository=Path("/unused"))

        def acquire(value):
            value.proxy_lock = SimpleNamespace(shared=False)

        with mock.patch.dict(os.environ, CODEX_SANDBOX_QUIET_NOTICES=""), \
                mock.patch.dict(execute.__globals__, validate_repository=mock.Mock(),
                                recover_relays=mock.Mock(), acquire_lock=acquire,
                                load_repository_policy=mock.Mock(),
                                stage_skills=mock.Mock(side_effect=RuntimeError("stop after notice"))), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, "stop after notice"):
                execute(state)
        self.assertIn(
            "Checking sandbox images and preparing services from current repository policy; "
            "cached resources are reused when valid; builds run only when needed.",
            output.getvalue(),
        )

    def test_test_quiet_mode_suppresses_launcher_notices(self) -> None:
        notice = runpy.run_path(str(LAUNCHER))["launcher_notice"]
        with mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            notice("hidden during tests")
        self.assertEqual("", output.getvalue())

    def test_session_authority_precedes_policy_loading(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        state = SimpleNamespace(repository=Path("/unused"))
        observed = []

        def acquire(value):
            observed.append("lock")
            value.proxy_lock = SimpleNamespace(shared=False)

        def load(value):
            self.assertIs(value, state)
            observed.append("policy")
            raise RuntimeError("stop after ordering proof")

        with mock.patch.dict(execute.__globals__, validate_repository=mock.Mock(),
                             acquire_lock=acquire, load_repository_policy=load):
            with self.assertRaisesRegex(RuntimeError, "ordering proof"):
                execute(state)
        self.assertEqual(["lock", "policy"], observed)

    def test_shared_session_loads_accepted_authority_without_repository_policy(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        state = SimpleNamespace(repository=Path("/unused"))

        def acquire(value):
            value.proxy_lock = SimpleNamespace(shared=True)

        policy = mock.Mock(side_effect=AssertionError("join read repository policy"))
        with mock.patch.dict(os.environ, CODEX_SANDBOX_QUIET_NOTICES=""), \
                mock.patch.dict(execute.__globals__, validate_repository=mock.Mock(),
                                recover_relays=mock.Mock(), acquire_lock=acquire,
                                load_accepted_session=mock.Mock(), load_repository_policy=policy,
                                stage_skills=mock.Mock(side_effect=RuntimeError("stop after notice"))), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, "stop after notice"):
                execute(state)
        policy.assert_not_called()
        self.assertIn(
            "Reusing accepted sandbox image and proxies; repository image changes apply "
            "after all attached sessions exit.",
            output.getvalue(),
        )

    def test_bake_only_repository_rejects_podman_before_startup_effects(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))['execute']
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            producer = repository / '.agents/sandbox/bake'
            producer.parent.mkdir(parents=True)
            producer.touch()
            stage = mock.Mock()
            acquire = mock.Mock(side_effect=lambda state: setattr(
                state, 'proxy_lock', SimpleNamespace(shared=False)))
            with mock.patch.dict(execute.__globals__, OUTER_RUNTIME=SimpleNamespace(provider='container'),
                                 validate_repository=mock.Mock(), acquire_lock=acquire,
                                 load_repository_policy=mock.Mock(), stage_skills=stage):
                with self.assertRaisesRegex(execute.__globals__['LauncherError'], 'CODEX_SANDBOX_RUNTIME=lima-docker'):
                    execute(SimpleNamespace(repository=repository))
            stage.assert_not_called()

    def test_docker_startup_resolves_bake_targets_before_container_workers(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))['execute']
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            builder = repository / '.agents/sandbox/bake'
            builder.parent.mkdir(parents=True)
            builder.touch(mode=0o755)
            manifest = repository / 'manifest.json'
            manifest.write_text('{"commands": {"bug": {"image-target": "bb-bug"}}}')
            state = SimpleNamespace(repository=repository, agent_docker=None, uid=501, gid=20,
                                    codex_arguments=[], deferred_signal=None, manifest=manifest)
            replacements = {name: mock.Mock(return_value=[]) for name in (
                'validate_repository', 'stage_skills', 'register_tmux_pane', 'ensure_network',
                'acquire_lock', 'prepare_gateway', 'start_gateway', 'start_keychain', 'attach_proxies')}
            replacements['acquire_lock'].side_effect = lambda value: setattr(
                value, 'proxy_lock', SimpleNamespace(shared=False))
            replacements['load_repository_policy'] = mock.Mock()
            prepared = SimpleNamespace(base='base@digest', auth='auth@digest', proxies={'bug': 'bug@digest'})
            def prepare(*args, **kwargs):
                replacements['ensure_network'].assert_not_called()
                replacements['attach_proxies'].assert_not_called()
                return prepared
            preparation = mock.Mock(side_effect=prepare)
            replacements.update(OUTER_RUNTIME=SimpleNamespace(provider='lima-docker',
                prepare_images=mock.Mock(side_effect=AssertionError('runtime owns no image composition'))),
                prepare_launch_images=preparation,
                temporary_file=lambda: repository / 'images.json',
                resolve_agent=mock.Mock(return_value='agent@digest'),
                resolve_sidecar_image=mock.Mock(return_value='auth@digest'),
                run=mock.Mock(return_value=SimpleNamespace(stdout='base@digest')),
                run_agent=mock.Mock(return_value=0))
            with mock.patch.dict(execute.__globals__, replacements):
                self.assertEqual(0, execute(state))
                replacements['resolve_agent'].assert_called_once_with(
                    replacements['OUTER_RUNTIME'], state.uid, state.gid, 'base@digest')
                self.assertEqual(json.loads(state.prepared_images.read_text()), prepared.proxies)
                self.assertEqual(state.sidecar_image, prepared.auth)
                self.assertIn('agent@digest', replacements['run_agent'].call_args.args[1])
                preparation.side_effect = ValueError('image validation failed')
                replacements['attach_proxies'].reset_mock()
                replacements['run_agent'].reset_mock()
                with self.assertRaisesRegex(ValueError, 'image validation failed'):
                    execute(state)
                replacements['attach_proxies'].assert_not_called()
                replacements['run_agent'].assert_not_called()
                preparation.side_effect = None
                preparation.return_value = prepared
                replacements['resolve_agent'].side_effect = ValueError('build failed')
                replacements['run_agent'].reset_mock()
                with self.assertRaisesRegex(ValueError, 'build failed'):
                    execute(state)
                replacements['run_agent'].assert_not_called()
                preparation.side_effect = ValueError('builder batch failed')
                replacements['ensure_network'].reset_mock()
                with self.assertRaisesRegex(ValueError, 'builder batch failed'):
                    execute(state)
                replacements['ensure_network'].assert_not_called()
                preparation.side_effect = OSError("[Errno 2] No such file or directory: '/src'")
                with self.assertRaisesRegex(
                    execute.__globals__['LauncherError'],
                    r"image preparation failed: .*'/src'",
                ):
                    execute(state)

    def test_signal_during_image_build_waits_before_proxy_cleanup(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        # Exercise the primary owner body below the early-fork frontend. This
        # test intentionally creates an in-process thread that sends its signal.
        main = launcher["launch"]
        build_release = threading.Event()
        build_finished = threading.Event()
        proxy_attached = threading.Event()

        with tempfile.TemporaryDirectory() as directory:
            state = SimpleNamespace(
                repository=Path(directory), agent_docker=None, uid=501, gid=20, codex_arguments=[],
                joining_workers=False, deferred_signal=None,
            )

            def resolve_agent(_runtime, _uid, _gid, _base_image):
                if not build_release.wait(5):
                    raise RuntimeError("test did not release image build")
                build_finished.set()
                return "image"

            def attach_proxies(_state):
                proxy_attached.set()
                return []

            def interrupt_after_proxy_attachment():
                if not proxy_attached.wait(2):
                    build_release.set()
                    return
                os.kill(os.getpid(), signal.SIGTERM)
                deadline = time.monotonic() + 2
                while not state.joining_workers and time.monotonic() < deadline:
                    time.sleep(0.01)
                build_release.set()

            replacements = {
                name: mock.Mock(return_value=[])
                for name in (
                    "validate_repository", "register_tmux_pane", "ensure_network",
                    "acquire_lock", "prepare_gateway", "stage_skills",
                )
            }
            replacements["acquire_lock"].side_effect = lambda value: setattr(
                value, "proxy_lock", SimpleNamespace(shared=False))
            replacements["load_repository_policy"] = mock.Mock()
            replacements.update(
                resolve_agent=resolve_agent,
                resolve_sidecar_image=mock.Mock(return_value="sidecar"),
                attach_proxies=attach_proxies,
                existing_git_root=mock.Mock(return_value=ROOT),
                run=mock.Mock(return_value=SimpleNamespace(stdout="Darwin")),
                start_gateway=mock.Mock(),
                run_agent=mock.Mock(side_effect=AssertionError("agent must not start")),
            )

            interrupter = threading.Thread(target=interrupt_after_proxy_attachment)

            def cleanup(_state):
                self.assertTrue(build_finished.is_set(), "cleanup raced the image build")

            with mock.patch.dict(
                main.__globals__,
                image_runtime=lambda: launcher['ContainerRuntime'](),
                new_state=lambda _: state,
                cleanup=cleanup,
                unregister_tmux_pane=lambda _: None,
            ), mock.patch.dict(launcher["execute"].__globals__, replacements):
                interrupter.start()
                try:
                    self.assertEqual(128 + signal.SIGTERM, main([]))
                finally:
                    build_release.set()
                    interrupter.join(5)
                self.assertFalse(interrupter.is_alive())

    def test_signal_during_join_cannot_race_cleanup(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        main = launcher["launch"]
        state = SimpleNamespace(joining_workers=False, deferred_signal=None)
        abort = threading.Event()
        finished = threading.Event()

        def relay():
            deadline = time.monotonic() + 2
            while not state.joining_workers:
                if abort.wait(0.01) or time.monotonic() >= deadline:
                    return
            os.kill(os.getpid(), signal.SIGTERM)
            while state.deferred_signal is None:
                if abort.wait(0.01) or time.monotonic() >= deadline:
                    return
            finished.set()

        def execute(_state):
            with launcher["startup_workers"](state, 1) as executor:
                executor.submit(relay)
            return 0

        def cleanup(_state):
            self.assertTrue(finished.is_set(), "cleanup raced the relay worker")

        runtime = mock.Mock()
        with mock.patch.dict(main.__globals__, image_runtime=lambda: runtime,
                             new_state=lambda _: state, execute=execute, cleanup=cleanup,
                             unregister_tmux_pane=lambda _: None):
            try:
                self.assertEqual(128 + signal.SIGTERM, main([]))
            finally:
                abort.set()

    def test_agent_starts_before_relays_and_exit_joins_them(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        release = threading.Event()
        agent_started = threading.Event()
        complete = threading.Event()
        result = []

        def relay(_state):
            if not release.wait(5):
                raise RuntimeError("test did not release relay")
            raise RuntimeError("injected optional failure")

        def agent(_state, _arguments):
            agent_started.set()
            return 19

        with tempfile.TemporaryDirectory() as directory:
            state = SimpleNamespace(repository=Path(directory), agent_docker={}, uid=501, gid=20, codex_arguments=[],
                                    deferred_signal=None)
            replacements = {
                name: mock.Mock(return_value=[])
                for name in ("validate_repository", "register_tmux_pane", "ensure_network",
                             "acquire_lock", "attach_proxies", "prepare_gateway",
                             "stage_skills", "start_keychain")
            }
            replacements["acquire_lock"].side_effect = lambda value: setattr(
                value, "proxy_lock", SimpleNamespace(shared=False))
            replacements["load_repository_policy"] = mock.Mock()
            replacements["prepare_gateway"].side_effect = lambda value: (
                setattr(value, "gateway_handle", SimpleNamespace(
                    started=False, build_bridge=object())) or [])
            replacements.update(
                resolve_agent=mock.Mock(return_value="image"),
                resolve_sidecar_image=mock.Mock(return_value="sidecar"),
                run=mock.Mock(return_value=SimpleNamespace(stdout="Darwin")),
                start_gateway=relay, run_agent=agent,
            )

            def launch():
                try:
                    result.append(execute(state))
                finally:
                    complete.set()

            with mock.patch.dict(execute.__globals__, replacements), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as output:
                thread = threading.Thread(target=launch)
                thread.start()
                try:
                    self.assertTrue(agent_started.wait(2), "Pi waited for optional relays")
                    self.assertFalse(complete.wait(0.1), "cleanup can race relay creation")
                finally:
                    release.set()
                    thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual([19], result)
                self.assertEqual(1, output.getvalue().count("injected optional failure"))


class AgentSandboxImageTest(unittest.TestCase):
    def test_image_creates_source_mount_point_before_chown(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "mkdir -p ${HOME}/.pi/agent ${HOME}/.codex /src /workspace",
            dockerfile,
        )

    def test_pi_build_uses_lockfile_pinned_model_data(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("npm run hydrate:pinned-model-data", dockerfile)
        self.assertNotIn("npm run hydrate:model-data", dockerfile)

    def test_image_installs_guest_clients_and_uses_local_editor(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "./tools/zulip-proxy/client ./tools/zulip-proxy/protocol.json "
            "/tools/zulip-proxy/",
            dockerfile,
        )
        self.assertIn("ENV EDITOR=vi VISUAL=vi", dockerfile)

    def test_woodpecker_adapter_remains_visible_after_bb_resolves_its_wrapper(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "COPY --chown=${AGENT_UID}:${AGENT_GID} "
            "./tools/agent-docker/woodpecker-cli "
            "/opt/agent-tools/bin/woodpecker-cli",
            dockerfile,
        )

    def test_login_profile_restores_agent_wrappers_path(self) -> None:
        result = subprocess.run(
            ["sh", "-c", f'. "{AGENT_WRAPPERS_PROFILE}"; printf "%s\\n" "$PATH"'],
            env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(
            "/libexec/sandbox-wrappers:/libexec/agent-wrappers:/usr/local/bin:/usr/bin:/bin\n",
            result.stdout,
        )
    def test_dotfiles_profile_sets_a_noninteractive_environment(self) -> None:
        result = subprocess.run(
            [
                "sh",
                "-c",
                f'. "{DOTFILES_PROFILE}"; '
                'printf "%s\\n" "$DOTFILES_SANDBOX|$MAKEFLAGS|$PAGER|$EDITOR|$CARGO_HOME"',
            ],
            env={"HOME": "/sandbox-home", "PATH": "/usr/bin:/bin"},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(
            "1|-j4|cat|vi|/sandbox-home/.local/lib/cargo\n", result.stdout
        )

        path_result = subprocess.run(
            ["sh", "-c", f'. "{DOTFILES_PROFILE}"; printf "%s\\n" "$PATH"'],
            env={"HOME": "/sandbox-home", "PATH": "/usr/local/bin:/usr/bin:/bin"},
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(
            "/libexec/sandbox-wrappers:/libexec/agent-wrappers:/opt/agent-tools/bin:/opt/agent-pi/bin:"
            "/usr/local/bin:/usr/bin:/bin\n",
            path_result.stdout,
        )

    def test_sandbox_gitconfig_keeps_diff_semantics_without_identity_or_credentials(self) -> None:
        result = subprocess.run(
            ["git", "config", "--file", str(SANDBOX_GITCONFIG), "--get", "diff.algorithm"],
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        self.assertEqual("histogram\n", result.stdout)
        config = SANDBOX_GITCONFIG.read_text(encoding="utf-8")
        self.assertNotIn("[user]", config)
        self.assertNotIn("[credential]", config)


class CodexSandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo with spaces"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".jj" / "repo").mkdir(parents=True)
        self.home = self.root / "home with spaces"
        (self.home / ".agents" / "skills").mkdir(parents=True)
        (self.home / ".codex" / "rules").mkdir(parents=True)
        (self.home / "src").mkdir()
        self.pi_package = (
            self.home / ".local/share/pi/node/node_modules/@earendil-works/pi-coding-agent"
        )
        (self.pi_package / "dist/bundle").mkdir(parents=True)
        shutil.copyfile(Path(__file__).with_name("host_pi_cli_fixture.mjs"),
                        self.pi_package / "dist/bundle/cli.js")
        (self.pi_package / "dist/bundle/cli.js").chmod(0o700)
        (self.pi_package / "README.md").write_text("host readme\n", encoding="utf-8")
        (self.pi_package / "docs").mkdir()
        (self.pi_package / "examples").mkdir()
        pi_cli = self.home / ".local/share/pi/node/node_modules/.bin/pi"
        pi_cli.parent.mkdir(parents=True, exist_ok=True)
        pi_cli.symlink_to(self.pi_package / "dist/bundle/cli.js")
        self.pi_revision = 'a' * 40
        self.pi_marker = self.home / '.local/share/pi/node/.source-revision'
        self.pi_marker.write_text(self.pi_revision + '\n')
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        if NATIVE_TMUX is not None:
            # Fake Python is only the proxy boundary. Host wrapper shebangs must
            # not turn native tmux calls into fake proxy-helper invocations.
            (self.fake_bin / "tmux").symlink_to(NATIVE_TMUX)
        self.docker_log = self.root / "docker.log"
        self.python_log = self.root / "python.log"
        self.codex_log = self.root / "codex.log"
        self.jj_log = self.root / "jj.log"

        write_executable(self.fake_bin / "codex", """
            #!/bin/sh
            printf '%s\t%s\t%s\n' "$CODEX_HOME" "$CODEX_DEVELOPER_INSTRUCTIONS_FILE" "$*" > "$FAKE_CODEX_LOG"
        """)
        write_executable(self.fake_bin / "jj", """
            #!/bin/sh
            {
                printf 'CALL'
                for argument do printf '\t%s' "$argument"; done
                printf '\n'
            } >> "$FAKE_JJ_LOG"
            if [ "$1 $2" = "git init" ]; then
                mkdir -p "$FAKE_REPOSITORY/.git" "$FAKE_REPOSITORY/.jj/repo"
                exit
            fi
            if [ "$1 $2" = "workspace root" ]; then
                [ -d "$FAKE_REPOSITORY/.jj" ] || exit 1
                printf '%s\n' "$FAKE_REPOSITORY"
                exit
            fi
            if [ "$1 $2" = "git root" ]; then
                printf '%s\n' "${FAKE_GIT_ROOT:-$FAKE_REPOSITORY}"
                exit
            fi
            exit 2
        """)
        write_executable(self.fake_bin / "git", """
            #!/bin/sh
            case " $* " in
                *" rev-parse --show-toplevel "*)
                    [ -e "$FAKE_REPOSITORY/.git" ] || exit 1
                    printf '%s\n' "$FAKE_REPOSITORY"
                    ;;
                *" rev-parse "*)
                    printf '%s\n%s\n' "${FAKE_GIT_DIR:-$FAKE_REPOSITORY/.git}" \
                        "${FAKE_GIT_COMMON_DIR:-$FAKE_REPOSITORY/.git}"
                    ;;
                *) exec /usr/bin/git "$@" ;;
            esac
        """)
        write_executable(self.fake_bin / "uname", """
            #!/bin/sh
            printf '%s\n' "${FAKE_UNAME:-Linux}"
        """)
        write_executable(self.fake_bin / "docker", """
            #!/bin/sh
            tab=$(printf '\t')
            record=CALL
            for argument do record="${record}${tab}${argument}"; done
            printf '%s\n' "$record" >> "$FAKE_DOCKER_LOG"
            if [ "$1 $2" = "network exists" ]; then
                [ "${FAKE_NETWORK_EXISTS:-1}" = 1 ]
                exit
            fi
            if [ "$1 $2" = "network create" ] && [ "${FAKE_NETWORK_CREATE_FAIL:-0}" = 1 ]; then
                exit 44
            fi
            # The fake engine has no listed relay resources; inspect must agree.
            if [ "$1 $2" = "container inspect" ]; then exit 1; fi
            if [ "$1 $2" = "network inspect" ]; then
                case " $* " in *"index .Labels"*) exit 1 ;; esac
                printf '%s\n' 127.0.0.1
                exit
            fi
            if [ "$1 $2" = "info --format" ]; then
                printf '%s\n' linux/amd64
                exit
            fi
            if [ "$1 $2" = "image exists" ]; then
                [ "${FAKE_IMAGE_EXISTS:-1}" = 1 ] || [ -f "$FAKE_DOCKER_LOG.$3" ]
                exit
            fi
            if [ "$1 $2" = "image inspect" ]; then
                case " $* " in
                    *"dev.codex.pi-revision"*) printf '%s\n' "$FAKE_IMAGE_PI_REVISION"; exit 0 ;;
                esac
                for image do :; done
                if [ "${FAKE_IMAGE_EXISTS:-1}" != 1 ] && [ "${image#codex-sandbox:}" != "$image" ] && [ ! -f "$FAKE_DOCKER_LOG.$image" ]; then
                    exit 1
                fi
                case " $* " in
                    *" --format "*) printf 'sha256:%064d\n' 0; exit 0 ;;
                esac
                case "$image" in
                    caddy@sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba)
                        printf '%s\n' '[{"Id":"sha256:6b08c1b9858ca9a7d99c1da13c3695081e0e604c6cf214ca26a7ce0e2c4fd9b4","RepoDigests":["caddy@sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba"],"RootFS":{"Layers":["sha256:0000000000000000000000000000000000000000000000000000000000000001"]},"Os":"linux","Architecture":"amd64"}]'
                        ;;
                    *) printf '[{"Id":"sha256:%064d","RootFS":{"Layers":["sha256:%064d"]},"Os":"linux","Architecture":"amd64"}]\n' 0 1 ;;
                esac
                exit 0
            fi
            if [ "$1" = build ]; then
                previous=
                for argument do
                    if [ "$previous" = --tag ]; then
                        : > "$FAKE_DOCKER_LOG.$argument"
                    fi
                    previous=$argument
                done
                previous=
                for argument do
                    if [ "$previous" = --iidfile ]; then
                        printf '%s\n' 'sha256:built-image-id' > "$argument"
                        break
                    fi
                    previous=$argument
                done
                exit 0
            fi
            if [ "$1" = create ]; then
                container=
                worker=0
                agent_dir=
                previous=
                for argument do
                    [ "$previous" = --name ] && container=$argument
                    [ "$argument" = /opt/agent-tools/bin/tool-worker.mjs ] && worker=1
                    case "$argument" in
                        type=bind,src=*,dst=/home/codex/.pi/agent)
                            agent_dir=${argument#type=bind,src=}
                            agent_dir=${agent_dir%,dst=*}
                            ;;
                    esac
                    previous=$argument
                done
                if [ "$worker" = 1 ]; then
                    printf '%s\n' "$agent_dir" > "$FAKE_DOCKER_LOG.worker.$container"
                fi
                exit 0
            fi
            if [ "$1" = start ]; then
                container=
                for argument do container=$argument; done
                marker="$FAKE_DOCKER_LOG.worker.$container"
                if [ -f "$marker" ]; then
                    if [ "${FAKE_WORKER_EXIT+x}" = x ]; then
                        exit "$FAKE_WORKER_EXIT"
                    fi
                    agent_dir=$(head -n 1 "$marker")
                    if [ -n "$agent_dir" ]; then
                        (umask 077; : > "$agent_dir/tool-worker-ready")
                        [ -z "$FAKE_WORKER_READY_POST_CREATE_DELAY" ] || sleep "$FAKE_WORKER_READY_POST_CREATE_DELAY"
                    fi
                    if [ -n "$FAKE_AGENT_READY" ]; then : > "$FAKE_AGENT_READY"; fi
                    # Keep the worker alive until removal without adding a
                    # one-second shutdown delay to every launcher test.
                    while [ -f "$marker" ]; do sleep 0.01; done
                fi
                exit 0
            fi
            if [ "$1" = inspect ]; then
                case " $* " in
                    *" {{.State.Running}} "*) printf '%s\n' true ;;
                    *"if index"*"NetworkSettings.Networks"*)
                        [ "${FAKE_SIDECAR_NETWORK:-1}" = 1 ] && printf '%s\n' true
                        ;;
                    *) printf '%s\n' "${FAKE_RELAY_IP:-10.0.0.9}" ;;
                esac
                exit 0
            fi
            if [ "$1" = run ]; then
                case " $* " in
                    *" -it "*)
                        if [ -n "$FAKE_MODEL_STORE_CAPTURE" ]; then
                            for argument do
                                case "$argument" in
                                    type=bind,src=*,dst=/home/codex/.pi/agent)
                                        agent_dir=${argument#type=bind,src=}
                                        agent_dir=${agent_dir%,dst=*}
                                        cp "$agent_dir/models-store.json" "$FAKE_MODEL_STORE_CAPTURE" || exit 42
                                        printf '{}\\n' > "$agent_dir/models-store.json"
                                        ;;
                                esac
                            done
                        fi
                        if [ "${FAKE_AGENT_BLOCK:-0}" = 1 ]; then
                            : > "$FAKE_AGENT_READY"
                            trap 'exit 143' HUP INT TERM
                            while :; do sleep 1; done
                        fi
                        exit "${FAKE_AGENT_EXIT:-0}"
                        ;;
                esac
                exit 0
            fi
            if [ "$1" = rm ] && [ -n "$FAKE_CLEANUP_DELAY" ]; then
                sleep "$FAKE_CLEANUP_DELAY"
            fi
            if [ "$1" = rm ]; then
                container=
                for argument do container=$argument; done
                rm -f "$FAKE_DOCKER_LOG.worker.$container"
            fi
            exit 0
        """)
        write_executable(self.fake_bin / "python3", """
            #!/bin/sh
            # Repository builders now use the image helper's single-reference
            # protocol. Keep the launch test independent of a real image build.
            case "$1" in
                */owned_images.py|*/sandbox-image) printf 'sha256:%064d\\n' 0; exit 0 ;;
                */sandbox-host-pi) exec /usr/bin/python3 "$@" ;;
            esac
            {
                printf 'CALL'
                for argument do printf '\t%s' "$argument"; done
                printf '\n'
            } >> "$FAKE_PYTHON_LOG"
            action=$2
            shift 2
            value_for() {
                wanted=$1
                shift
                while [ "$#" -gt 0 ]; do
                    if [ "$1" = "$wanted" ]; then printf '%s\n' "$2"; return; fi
                    shift
                done
                return 1
            }
            case "$action" in
                snapshot)
                    output=$(value_for --output "$@")
                    printf '%s\n' '{"version":1,"capabilities":{"host-editor":true,"nested-containers":true},"commands":{"jj":{},"zulip":{}}}' > "$output"
                    ;;
                join)
                    state=$(value_for --state "$@")
                    manifest=$(value_for --manifest "$@")
                    images=$(value_for --images "$@")
                    accepted=$(value_for --accepted "$@")
                    if [ -n "$FAKE_PROXY_STATE" ]; then
                        printf '%s\n' "$FAKE_PROXY_STATE" > "$state"
                    else
                        printf '%s\n' '{"proxies":[]}' > "$state"
                    fi
                    printf '%s\n' '{"version":1,"capabilities":{"host-editor":true,"nested-containers":true},"commands":{"jj":{}}}' > "$manifest"
                    printf '%s\n' '{"jj":"sha256:0000000000000000000000000000000000000000000000000000000000000000"}' > "$images"
                    printf '%s\n' '{"source-present":true,"agent-image":"sha256:0000000000000000000000000000000000000000000000000000000000000000","helper-image":"sha256:0000000000000000000000000000000000000000000000000000000000000000"}' > "$accepted"
                    ;;
                attach)
                    state=$(value_for --state "$@")
                    if [ -n "$FAKE_PROXY_STATE" ]; then
                        printf '%s\n' "$FAKE_PROXY_STATE" > "$state"
                    else
                        printf '%s\n' '{"proxies":[]}' > "$state"
                    fi
                    ;;
                agent-args|finalize)
                    output=$(value_for --output "$@")
                    printf '%s\n' '--env' 'SANDBOX_PROXY_DIR=/run/sandbox-proxies' > "$output"
                    ;;
                publish|monitor|stop) ;;
                *) exit 91 ;;
            esac
        """)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def launcher_environment(self, **updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("TMUX", None)
        environment.pop("TMUX_PANE", None)
        environment.update({
            "PATH": f"{self.fake_bin}:{environment['PATH']}",
            "HOME": str(self.home),
            "FAKE_REPOSITORY": str(self.repo),
            "FAKE_DOCKER_LOG": str(self.docker_log),
            "FAKE_PYTHON_LOG": str(self.python_log),
            "FAKE_CODEX_LOG": str(self.codex_log),
            "FAKE_JJ_LOG": str(self.jj_log),
            "AGENT_DOCKER_ACCESS_DIR": str(self.root / "no-agent-docker"),
            "FAKE_NETWORK_EXISTS": "1",
            "FAKE_UNAME": "Linux",
            "FAKE_IMAGE_PI_REVISION": self.pi_revision,
        })
        environment.update(updates)
        return environment

    def run_launcher(
        self, *arguments: str, cwd: Path | None = None, **updates: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(LAUNCHER_FIXTURE), *arguments], cwd=cwd or self.repo,
            env=self.launcher_environment(**updates),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )

    def final_run(self) -> list[str]:
        creates = [call for call in read_calls(self.docker_log)
                   if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]
        self.assertEqual(1, len(creates))
        return creates[0]

    def test_mounts_host_skills_writable_through_resolved_source(self) -> None:
        skills = self.home / ".agents" / "skills"
        skills.rmdir()
        source = self.root / "tracked-skills"
        shutil.copytree(ROOT / "skills", source)
        skills.symlink_to(source, target_is_directory=True)
        relative_reference = Path("references/change-with-evidence.md")
        reference = source / relative_reference
        self.assertEqual((ROOT / "skills" / relative_reference).read_bytes(), reference.read_bytes())

        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(
            home=self.home, repository=self.repo, skills_tmp=None, skills_source=None,
        )
        try:
            launcher["stage_skills"](state)
            self.assertEqual(source, state.skills_source)
            self.assertFalse((state.skills_tmp / "skills").exists())
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        mount = f"type=bind,src={source},dst=/home/codex/.agents/skills"
        self.assertIn(mount, self.final_run())
        self.assertNotIn(mount + ",readonly", self.final_run())
        self.assertFalse(any("change-with-evidence.md" in argument for argument in self.final_run()),
                         "the existing whole-directory mount carries references, not a new file mount")
        # The fake runtime proves mount selection, not a real guest read. Inspect
        # its live bind source directly: no staged copy or launcher rerun needed.
        revision = reference.read_bytes() + b"\nLive reference revision.\n"
        reference.write_bytes(revision)
        self.assertEqual(revision, (state.skills_source / relative_reference).read_bytes())
        self.assertEqual(revision, (skills / relative_reference).read_bytes())

    def test_host_pi_marks_guest_as_tool_worker(self) -> None:
        result = self.run_launcher(FAKE_WORKER_EXIT="17")
        self.assertNotEqual(0, result.returncode)  # The fake worker exits before Pi starts.
        creates = [call for call in read_calls(self.docker_log)
                   if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]
        self.assertEqual(1, len(creates), result.stderr)
        self.assertIn("CODEX_SANDBOX_TOOL_WORKER=1", creates[0])

    def test_worker_readiness_is_private_when_first_published(self) -> None:
        result = self.run_launcher(FAKE_WORKER_READY_POST_CREATE_DELAY="0.1")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_host_pi_skill_paths_are_readable_by_guest_tools(self) -> None:
        skills = self.home / ".agents/skills"
        skills.rmdir()
        source = self.root / "tracked-skills"
        source.mkdir()
        skills.symlink_to(source, target_is_directory=True)
        result = self.run_launcher(FAKE_WORKER_EXIT="17")
        self.assertNotEqual(0, result.returncode)  # The fake worker exits before Pi starts.
        creates = [call for call in read_calls(self.docker_log)
                   if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]
        self.assertEqual(1, len(creates), result.stderr)
        self.assertIn(
            f"type=bind,src={source},dst=/home/codex/.agents/skills",
            creates[0],
        )
        self.assertNotIn(
            f"type=bind,src={source},dst={skills}",
            creates[0],
        )

    def test_host_pi_resources_use_guest_paths(self) -> None:
        result = self.run_launcher(FAKE_WORKER_EXIT="17")

        self.assertNotEqual(0, result.returncode)  # The fake worker exits before Pi starts.
        creates = [call for call in read_calls(self.docker_log)
                   if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]
        self.assertEqual(1, len(creates), result.stderr)
        guest = Path("/opt/agent-pi/src/packages/coding-agent")
        for relative in ("README.md", "docs", "examples"):
            self.assertIn(
                f"type=bind,src={self.pi_package / relative},dst={guest / relative},readonly",
                creates[0],
            )

    def test_staging_uses_install_mapping_for_config_source_names(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        checkout = self.root / "alternate-dotfiles"
        renamed = checkout / "renamed-pi-config/breq.md"
        renamed.parent.mkdir(parents=True)
        renamed.write_text("renamed source\n", encoding="utf-8")
        sources = launcher["installed_config_sources"]()
        mappings = {target: str(source) for target, source in sources.items()
                    if target != "$HOME/.pi/agent/breq.md"}
        mappings["$HOME/.pi/agent/"] = {"glob": True, "path": "renamed-pi-config/**"}
        (checkout / "install.conf.json").write_text(json.dumps([{"link": mappings}]))
        launcher["installed_config_sources"].cache_clear()
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            with mock.patch.dict(launcher["stage_skills"].__globals__, {"DOTFILES": checkout}):
                launcher["stage_skills"](state)
            self.assertEqual(
                "renamed source\n",
                (state.skills_tmp / "config/breq").read_text(encoding="utf-8"),
            )
        finally:
            launcher["installed_config_sources"].cache_clear()
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

    def test_stages_home_sandbox_references_without_guest_pi_instructions(self) -> None:
        repository_sandbox = self.repo / ".agents" / "sandbox"
        repository_sandbox.mkdir(parents=True)
        (repository_sandbox / "AGENTS.md").write_text(
            "@repository-rule.md\n", encoding="utf-8",
        )
        (repository_sandbox / "repository-rule.md").write_text(
            "repository rule\n", encoding="utf-8",
        )
        home_sandbox = self.home / ".agents" / "sandbox"
        home_sandbox.mkdir()
        (home_sandbox / "AGENTS.md").write_text(
            "@home-rule.md\n", encoding="utf-8",
        )
        (home_sandbox / "home-rule.md").write_text(
            "home rule\n", encoding="utf-8",
        )

        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(
            home=self.home, repository=self.repo,
            container_repository=Path("/src/repository"), skills_tmp=None,
        )
        try:
            launcher["stage_skills"](state)
            self.assertFalse((state.skills_tmp / "config/agents").exists())
            self.assertEqual(
                "home rule\n",
                (state.skills_tmp / "sandbox/home-rule.md").read_text(encoding="utf-8"),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(
            item.endswith("dst=/home/codex/.agents/sandbox,readonly")
            for item in self.final_run()
        ))
        self.assertFalse(any(
            "dst=/home/codex/.pi/agent/AGENTS.md" in item
            for item in self.final_run()
        ))

    def test_staged_settings_preserve_native_external_editor_selection(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            settings = json.loads(
                (state.skills_tmp / "config/settings").read_text(encoding="utf-8")
            )
            source = json.loads(launcher["installed_config_source"](
                "$HOME/.pi/agent/settings.json"
            ).read_text(encoding="utf-8"))
            self.assertEqual(source, settings)
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

    def test_mounts_subagent_configuration_from_staged_dotfiles(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            staged = state.skills_tmp / "config/subagents"
            self.assertEqual(
                json.loads(launcher["installed_config_source"](
                    "$HOME/.pi/agent/pi-codex-subagents/config.json"
                ).read_text(encoding="utf-8")),
                json.loads(staged.read_text(encoding="utf-8")),
            )
            models = state.skills_tmp / "config/models"
            source = launcher["installed_config_source"](
                "$HOME/.pi/agent/pi-codex-subagents/agents"
            )
            self.assertTrue(models.is_dir())
            self.assertEqual(
                (source / "luna.md").read_text(encoding="utf-8"),
                (models / "luna.md").read_text(encoding="utf-8"),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertTrue(any(
            item.endswith(
                "/config/subagents,dst=/home/codex/.pi/agent/"
                "pi-codex-subagents/config.json,readonly"
            )
            for item in run
        ))
        self.assertTrue(any(
            item.endswith(
                "/config/models,dst=/home/codex/.pi/agent/"
                "pi-codex-subagents/agents,readonly"
            )
            for item in run
        ))

    def test_mounts_subagent_transcripts_read_only_from_persistent_host_storage(self) -> None:
        runs = self.home / ".pi/agent/pi-codex-subagents/runs"
        self.assertFalse(runs.exists())
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(runs.is_dir())
        self.assertEqual(0o700, stat.S_IMODE(runs.stat().st_mode))
        self.assertEqual(
            [f"type=bind,src={runs},"
             "dst=/home/codex/.pi/agent/pi-codex-subagents/runs,readonly"],
            [argument for argument in self.final_run()
             if "dst=/home/codex/.pi/agent/pi-codex-subagents/runs" in argument],
        )
        transcript = runs / "parent" / "child.jsonl"
        transcript.parent.mkdir()
        transcript.write_text("existing conversation\n")
        runs.chmod(0o750)
        repeated = self.run_launcher()
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual("existing conversation\n", transcript.read_text())
        self.assertEqual(0o750, stat.S_IMODE(runs.stat().st_mode))

    def test_invalid_subagent_transcript_storage_stops_before_worker_creation(self) -> None:
        runs = self.home / ".pi/agent/pi-codex-subagents/runs"
        runs.parent.mkdir(parents=True)
        external = self.root / "external-run-storage"
        external.mkdir()
        marker = external / "keep"
        marker.write_text("existing data\n")
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    runs.write_text("not a directory\n")
                else:
                    runs.symlink_to(external, target_is_directory=True)
                try:
                    result = self.run_launcher()
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("Pi persistent directory is invalid", result.stderr)
                    self.assertIn(str(runs), result.stderr)
                    self.assertFalse(any(
                        call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call
                        for call in read_calls(self.docker_log)
                    ))
                    self.assertEqual("existing data\n", marker.read_text())
                finally:
                    runs.unlink()

    def test_launch_initializes_a_missing_jj_repository(self) -> None:
        shutil.rmtree(self.repo / ".jj")

        result = self.run_launcher()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.repo / ".jj" / "repo").is_dir())
        self.assertTrue((self.repo / ".git").is_dir())
        self.final_run()

    def test_fixture_initialization_never_uses_authoritative_checkout_metadata(self) -> None:
        shutil.rmtree(self.repo / ".jj")
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        initializations = [call for call in read_calls(self.jj_log) if call[:2] == ["git", "init"]]
        self.assertEqual([["git", "init", "--colocate", str(self.repo)]], initializations)
        command = self.final_run()
        metadata_sources = [item.split(",dst=", 1)[0].removeprefix("type=bind,src=")
                            for item in command if item.startswith("type=bind,src=")]
        self.assertFalse(any(Path(source).is_relative_to(ROOT / metadata)
                             for source in metadata_sources for metadata in (".jj", ".git")))
        # Restoring DOTFILES preserves real source paths for staged host code.
        self.assertIn(
            f"type=bind,src={ROOT / 'config/pi-agent/pi-extensions'},"
            "dst=/home/codex/.pi/agent/pi-extensions,readonly", command,
        )

    def test_git_subdirectory_initializes_jj_at_repository_root(self) -> None:
        shutil.rmtree(self.repo / ".jj")
        subdirectory = self.repo / "nested"
        subdirectory.mkdir()
        result = self.run_launcher(cwd=subdirectory)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(["git", "init", "--colocate", str(self.repo)], read_calls(self.jj_log))
        self.assertFalse((subdirectory / ".jj").exists())

    def test_bare_launch_gets_a_resumable_session_id(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        arguments, session_id = launcher["resumable_arguments"]([])
        self.assertEqual(["--session-id", session_id], arguments)
        self.assertRegex(session_id, r"^[0-9a-f-]{36}$")
        self.assertEqual(
            (["--session", "existing"], "existing"),
            launcher["resumable_arguments"](["--session", "existing"]),
        )
        self.assertEqual(
            (["--resume"], None),
            launcher["resumable_arguments"](["--resume"]),
        )

    def restart_registration(self, pane="%3", session_id="session-id", *, dead=False, cwd=None):
        cwd = cwd or self.repo
        directory = self.home / "custom sessions"
        directory.mkdir(exist_ok=True)
        session = directory / f"{session_id}.jsonl"
        session.write_text(json.dumps({"type": "session", "version": 3, "id": session_id,
                                       "timestamp": "2026-10-09T11:00:00.000Z", "cwd": str(cwd)}) + "\n")
        return {"version": 2, "pane": pane, "dead": dead, "pid": None if dead else 12345,
                "repository": str(self.repo), "session": str(session), "token": "token", "cwd": str(cwd)}

    def test_restart_checks_all_selected_artifacts_before_stopping_any_pane(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        first = self.restart_registration()
        valid = self.restart_registration("%4", "other-session")
        corrupt = self.root / "corrupt-session.jsonl"
        corrupt.write_text("not a Pi session\n")
        invalid = [
            ({**valid, "version": 1, "session": "launch-id"}, "run /reload"),
            ({**valid, "session": None}, "no saved Pi session"),
            ({**valid, "session": str(self.root / "missing.jsonl")}, "session file is missing"),
            ({**valid, "session": str(corrupt)}, "Cannot inspect Pi session.*No sessions were stopped"),
            ({**valid, "cwd": str(self.home)}, "working directories differ"),
        ]
        for registration, message in invalid:
            with self.subTest(message=message):
                run = mock.Mock()
                helper = mock.Mock()
                with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
                    launcher["restart_tmux_sessions"].__globals__, {
                        "tmux_registrations": lambda: [first, registration], "run": run, "helper": helper,
                    },
                ), mock.patch.object(os, "kill") as kill:
                    with self.assertRaisesRegex(launcher["LauncherError"], message):
                        launcher["restart_tmux_sessions"](self.repo)
                run.assert_not_called()
                helper.assert_not_called()
                kill.assert_not_called()

    def test_restart_all_stops_resets_and_relaunches_registered_panes(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        registrations = [self.restart_registration()]
        calls = []
        resets = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            # Pane-local lookup is empty when remain-on-exit is inherited.
            if arguments[:2] == ["tmux", "show-options"] and "-A" not in arguments:
                return SimpleNamespace(stdout="")
            return SimpleNamespace(stdout="off\n")

        function_globals = launcher["restart_tmux_sessions"].__globals__
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            function_globals, {
                "tmux_registrations": mock.Mock(side_effect=[registrations, []]),
                "run": fake_run,
                "helper": lambda *arguments: resets.append(arguments),
            },
        ), mock.patch.object(os, "kill") as kill:
            self.assertEqual(0, launcher["restart_tmux_sessions"]())
        kill.assert_called_once_with(12345, signal.SIGTERM)
        self.assertEqual([("reset", "--repo", str(self.repo), "--wait")], resets)
        self.assertIn(
            ["tmux", "set-option", "-p", "-t", "%3", "remain-on-exit", "on"],
            calls,
        )
        respawn = next(call for call in calls if call[:2] == ["tmux", "respawn-pane"])
        self.assertEqual(
            shlex.join(["cd", str(self.repo)]) + " && " + shlex.join(["pi", "--session", registrations[0]["session"]]),
            respawn[-1],
        )
        self.assertFalse(any(call[-1:] in (["C-c"], ["Enter"]) for call in calls))
        self.assertTrue(any(call[:2] == ["tmux", "display-message"] for call in calls))

    def test_restart_all_respawns_an_already_dead_registered_pane(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        registrations = [self.restart_registration(dead=True)]
        calls = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            return SimpleNamespace(stdout="off\n")

        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            launcher["restart_tmux_sessions"].__globals__, {
                "tmux_registrations": mock.Mock(side_effect=[registrations, registrations]),
                "run": fake_run,
                "helper": mock.Mock(),
            },
        ), mock.patch.object(os, "kill") as kill:
            self.assertEqual(0, launcher["restart_tmux_sessions"]())

        kill.assert_not_called()
        self.assertTrue(any(call[:2] == ["tmux", "respawn-pane"] for call in calls))

    @unittest.skipUnless(shutil.which("tmux"), "tmux is required")
    def test_failed_restart_preserves_registration_after_old_owner_cleanup_and_retries(self) -> None:
        for failure in ("reset", "respawn"):
            with self.subTest(failure=failure):
                launcher = runpy.run_path(str(LAUNCHER))
                socket_path = self.root / f"restart-recovery-{failure}.sock"
                prefix = ["tmux", "-S", str(socket_path)]

                def tmux(*arguments):
                    return subprocess.run([*prefix, *arguments], check=True,
                                          capture_output=True, text=True, timeout=10)

                environment = {"HOME": str(self.home), "TMUX": f"{socket_path},0,0"}
                try:
                    pane = tmux("-f", "/dev/null", "new-session", "-d", "-P", "-F", "#{pane_id}",
                                "-s", "recovery", "-c", str(self.repo), "sleep 30").stdout.strip()
                    tmux("new-session", "-d", "-s", "keepalive", "sleep 30")
                    state = SimpleNamespace(repository=self.repo, host_working_directory=self.repo,
                                            codex_arguments=["--resume"])
                    with mock.patch.dict(os.environ, {**environment, "TMUX_PANE": pane}):
                        launcher["register_tmux_pane"](state)
                        original = launcher["decode_tmux_registration"](state.tmux_registration)
                        selected = self.restart_registration(pane=pane, session_id=f"recover-{failure}")
                        saved = {**original, **{key: selected[key] for key in
                                 ("version", "pane", "repository", "session", "cwd")}}
                        encoded = base64.urlsafe_b64encode(json.dumps(saved).encode()).decode()
                        tmux("set-option", "-p", "-t", pane, "@codex_sandbox_restart", encoded)
                        real_kill = os.kill
                        real_run = launcher["run"]

                        def stop_old_owner(pid, signum):
                            # Cleanup runs with the old owner's original generation.
                            launcher["unregister_tmux_pane"](state)
                            real_kill(pid, signum)

                        def run(arguments, **kwargs):
                            if failure == "respawn" and arguments[:2] == ["tmux", "respawn-pane"]:
                                raise subprocess.CalledProcessError(1, arguments)
                            return real_run(arguments, **kwargs)

                        helper = mock.Mock()
                        if failure == "reset":
                            helper.side_effect = subprocess.CalledProcessError(1, ["reset"])
                        with mock.patch.dict(launcher["main"].__globals__, helper=helper, run=run), \
                                mock.patch.object(os, "kill", side_effect=stop_old_owner), \
                                contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(1, launcher["main"](["restart-all"]))
                        remaining = launcher["tmux_registrations"]()
                        self.assertEqual(1, len(remaining))
                        self.assertTrue(remaining[0]["dead"])
                        self.assertNotEqual(original["token"], remaining[0]["token"])
                        self.assertEqual(saved, {**{key: remaining[0][key] for key in saved},
                                                 "token": original["token"]})

                        # The actual tmux respawn accepts the saved retry record.
                        # Substitute a harmless child rather than launching a sandbox.
                        def resume(arguments, **kwargs):
                            if arguments[:2] == ["tmux", "respawn-pane"]:
                                expected = shlex.join(["cd", saved["cwd"]]) + " && " + \
                                           shlex.join(["pi", "--session", saved["session"]])
                                self.assertEqual(expected, arguments[-1])
                                arguments = [*arguments[:-1], "sleep 30"]
                            return real_run(arguments, **kwargs)

                        with mock.patch.dict(launcher["main"].__globals__, helper=mock.Mock(), run=resume), \
                                contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(0, launcher["main"](["restart-all"]))
                        self.assertFalse(launcher["tmux_registrations"]()[0]["dead"])
                finally:
                    subprocess.run([*prefix, "kill-server"], capture_output=True, timeout=10)

    def test_restart_repo_leaves_other_repositories_running(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        subdirectory = self.repo / "playground"
        subdirectory.mkdir()
        selected = [self.restart_registration("%3", "live-session", cwd=subdirectory),
                    self.restart_registration("%4", "dead-session", dead=True)]
        unrelated = {"pane": "%5", "dead": False, "pid": 54321,
                     "repository": str(self.root / "other-repo"), "session": "other-session"}
        calls = []
        resets = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            return SimpleNamespace(stdout="off\n")

        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            launcher["restart_tmux_sessions"].__globals__, {
                "tmux_registrations": mock.Mock(side_effect=[[*selected, unrelated], [unrelated]]),
                "run": fake_run,
                "helper": lambda *arguments: resets.append(arguments),
            },
        ), mock.patch.object(os, "kill") as kill, \
                mock.patch.object(time, "monotonic", side_effect=[0, 0.1, 30]), \
                mock.patch.object(time, "sleep"):
            self.assertEqual(0, launcher["main"](["restart", "--repo", str(self.repo)]))
        kill.assert_called_once_with(12345, signal.SIGTERM)
        self.assertEqual([("reset", "--repo", str(self.repo), "--wait")], resets)
        respawns = [call for call in calls if call[:2] == ["tmux", "respawn-pane"]]
        self.assertEqual(["%3", "%4"], [call[4] for call in respawns])
        self.assertEqual(
            [shlex.join(["cd", item["cwd"]]) + " && " + shlex.join(["pi", "--session", item["session"]])
             for item in selected],
            [call[-1] for call in respawns],
        )
        self.assertFalse(any("%5" in call for call in calls))

    @unittest.skipUnless(NATIVE_TMUX and shutil.which("node") and shutil.which("bun"),
                         "tmux, Node and Bun are required")
    def test_restart_uses_sdk_selected_file_with_real_tmux_and_pi_cli(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        socket_path = self.root / "restart-tmux.sock"
        prefix = [NATIVE_TMUX, "-S", str(socket_path)]
        # First check error retention with a failing native child, then forward the
        # exact resumed arguments to the installed Pi CLI to verify session identity.
        (self.fake_bin / "pi").symlink_to(TOOL / "tests/fixtures/restart_failure.mjs")
        environment = {"HOME": str(self.home), "FAKE_HOST_PI_READY": "", "FAKE_AGENT_EXIT": "0",
                       "PATH": str(self.fake_bin) + os.pathsep + os.environ["PATH"]}
        with mock.patch.dict(os.environ, environment):
            try:
                pane = subprocess.run(
                    [*prefix, "-f", "/dev/null", "new-session", "-d", "-P", "-F", "#{pane_id}",
                     "-s", "restart-test", "-c", str(self.repo), "sleep 30"],
                    check=True, capture_output=True, text=True,
                ).stdout.strip()
                subprocess.run([*prefix, "new-session", "-d", "-s", "keepalive", "sleep 30"],
                               check=True)
                state = SimpleNamespace(repository=self.repo, host_working_directory=self.repo,
                                        codex_arguments=["--resume"])
                with mock.patch.dict(os.environ, {"TMUX": f"{socket_path},0,0", "TMUX_PANE": pane}), \
                        mock.patch.dict(launcher["restart_tmux_sessions"].__globals__, {
                            "helper": mock.Mock(),
                        }):
                    launcher["register_tmux_pane"](state)
                    selected = self.restart_registration(session_id="persisted-session")
                    publication = subprocess.run(
                        ["bun", str(TOOL / "tests/publish_restart_fixture.ts"), selected["session"]],
                        check=True, capture_output=True, text=True,
                    )
                    cli = json.loads(publication.stdout)["cli"]
                    # A replaced generation must survive an old SDK publication.
                    current = launcher["tmux_registrations"]()[0]
                    replacement = {key: value for key, value in current.items() if key not in {"dead", "pid"}}
                    replacement["token"] = "replacement-generation"
                    encoded = base64.urlsafe_b64encode(json.dumps(replacement).encode()).decode()
                    subprocess.run(["bun", str(TOOL / "tests/publish_restart_fixture.ts"),
                                    selected["session"], encoded],
                                   check=True, capture_output=True, text=True)
                    self.assertEqual("replacement-generation", launcher["tmux_registrations"]()[0]["token"])
                    launcher["restart_tmux_sessions"](self.repo)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    result = subprocess.run(
                        [*prefix, "list-panes", "-a", "-F",
                         "#{pane_id}:#{pane_dead}:#{pane_dead_status}"],
                        check=True, capture_output=True, text=True,
                    )
                    status = next((line.split(":")[1:] for line in result.stdout.splitlines()
                                   if line.startswith(pane + ":")), None)
                    self.assertIsNotNone(status, f"failed restart destroyed pane {pane!r}: {result.stdout!r}")
                    if status == ["1", "23"]:
                        break
                    time.sleep(0.01)
                else:
                    self.fail("native restarted pane did not fail")
                result = subprocess.run([*prefix, "capture-pane", "-p", "-S", "-", "-t", pane],
                                        check=True, capture_output=True, text=True)
                self.assertIn("restart fixture: intentional Pi startup failure", result.stdout)
                # A retry must accept "failed", and successful exit must still close the pane.
                (self.fake_bin / "pi").unlink()
                fixture = TOOL / "tests/restart_pi_cli_fixture.mjs"
                (self.fake_bin / "pi").symlink_to(fixture)
                receipt = self.root / "resume-receipt.jsonl"
                subprocess.run([*prefix, "set-environment", "-g", "RESTART_PI_CLI", cli], check=True)
                subprocess.run([*prefix, "set-environment", "-g", "RESTART_PI_RECEIPT", str(receipt)], check=True)
                with mock.patch.dict(os.environ, {"TMUX": f"{socket_path},0,0"}), \
                        mock.patch.dict(launcher["restart_tmux_sessions"].__globals__, {
                            "helper": mock.Mock(),
                        }):
                    launcher["restart_tmux_sessions"](self.repo)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    panes = subprocess.run([*prefix, "list-panes", "-a", "-F", "#{pane_id}"],
                                           check=True, capture_output=True, text=True).stdout.splitlines()
                    if pane not in panes:
                        break
                    time.sleep(0.01)
                else:
                    status = subprocess.run([*prefix, "display-message", "-p", "-t", pane,
                                             "#{pane_dead}:#{pane_dead_status}:#{remain-on-exit}"],
                                            capture_output=True, text=True)
                    output = subprocess.run([*prefix, "capture-pane", "-p", "-S", "-", "-t", pane],
                                            capture_output=True, text=True)
                    self.fail(f"successful restarted UI exit kept its pane: {status.stdout}\n{output.stdout}")
                response = json.loads(receipt.read_text())
                self.assertTrue(response["success"])
                self.assertEqual(selected["session"], response["data"]["sessionFile"])
                self.assertEqual("persisted-session", response["data"]["sessionId"])
            finally:
                subprocess.run([*prefix, "kill-server"], capture_output=True)

    def test_restart_repo_waits_for_real_session_lock_after_pane_dies(self) -> None:
        self.assert_restart_waits_for_real_session_lock(["restart", "--repo", str(self.repo)])

    def test_restart_all_waits_for_real_session_lock_after_pane_dies(self) -> None:
        self.assert_restart_waits_for_real_session_lock(["restart-all"])

    def assert_restart_waits_for_real_session_lock(self, arguments: list[str]) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        environment = {"TMUX": "/tmp/tmux", "HOME": str(self.home)}
        with mock.patch.dict(os.environ, environment):
            proxies = launcher["proxy_module"]()
            proxies.use_repository_metadata(self.repo, (self.repo / ".git", self.repo / ".git"))
            runtime = proxies.runtime_directory(self.repo)
            holder = subprocess.Popen(
                [sys.executable, str(TOOL / "tests/session_lock_holder.py"), str(runtime / "session.lock")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            )
            try:
                self.assertEqual("ready\n", holder.stdout.readline())
                registration = self.restart_registration()
                real_flock = fcntl.flock
                contentions = []

                def observe_lock(file, operation):
                    try:
                        return real_flock(file, operation)
                    except BlockingIOError:
                        # The UI pane is already dead, but the detached owner still
                        # holds the real lifetime lock. Release only after observing it.
                        if not contentions:
                            holder.stdin.write("cleanup complete\n")
                            holder.stdin.flush()
                        contentions.append(operation)
                        raise

                with mock.patch.dict(launcher["main"].__globals__, {
                    "tmux_registrations": mock.Mock(side_effect=[
                        [registration], [{**registration, "dead": True}],
                    ]),
                    "run": mock.Mock(return_value=SimpleNamespace(stdout="off\n")),
                }), mock.patch.object(os, "kill"), mock.patch.object(fcntl, "flock", observe_lock), \
                        contextlib.redirect_stderr(io.StringIO()) as diagnostics:
                    result = launcher["main"](arguments)
                self.assertEqual(0, result, diagnostics.getvalue())
                self.assertIn("Waiting for sandbox cleanup:", diagnostics.getvalue())
                self.assertTrue(contentions)
                self.assertEqual("released\n", holder.stdout.readline())
                self.assertEqual(0, holder.wait(timeout=5))
            finally:
                holder.stdin.close()
                try:
                    holder.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.wait(timeout=5)
                holder.stdout.close()

    def test_restart_repo_without_matches_has_no_side_effects(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        run = mock.Mock()
        helper = mock.Mock()
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            launcher["restart_tmux_sessions"].__globals__, {
                "tmux_registrations": mock.Mock(return_value=[{
                    "repository": str(self.root / "other-repo"),
                }]),
                "run": run, "helper": helper,
            },
        ), mock.patch.object(os, "kill") as kill:
            with self.assertRaisesRegex(launcher["LauncherError"], "no registered sandbox sessions for"):
                launcher["restart_tmux_sessions"](self.repo)
        run.assert_not_called()
        helper.assert_not_called()
        kill.assert_not_called()

    def test_restart_cli_is_administrative_and_resolves_repository_alias(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        alias = self.root / "repo alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        restart = mock.Mock(return_value=0)
        with mock.patch("host_pi_owner.detached_frontend", side_effect=AssertionError("restart detached")), \
                mock.patch.dict(launcher["main"].__globals__, {"restart_tmux_sessions": restart}):
            self.assertEqual(0, launcher["main"](["restart", "--repo", str(alias)]))
            restart.assert_called_once_with(self.repo)
            restart.reset_mock()
            self.assertEqual(0, launcher["main"](["restart-all"]))
            restart.assert_called_once_with(None)

    def test_cache_clean_is_administrative_and_removes_the_owned_volume(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        runtime = object()
        clean = mock.Mock()
        with mock.patch(
                "host_pi_owner.detached_frontend",
                side_effect=AssertionError("cache cleanup detached")), \
                mock.patch.dict(launcher["main"].__globals__, {
                    "image_runtime": mock.Mock(return_value=runtime),
                    "clean_user_cache": clean,
                }), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, launcher["main"](["cache", "clean"]))
        clean.assert_called_once_with()
        self.assertIn("Sandbox user cache cleared.", output.getvalue())

    def test_cache_clean_uses_the_stable_volume_owner(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        runtime = object()
        remove = mock.Mock()
        with mock.patch.dict(launcher["clean_user_cache"].__globals__, {
                "OUTER_RUNTIME": runtime,
                "remove_owned_resource": remove,
        }):
            launcher["clean_user_cache"]()
        remove.assert_called_once_with(
            runtime, launcher["ResourceKind"].VOLUME,
            "codex-user-cache-v1", "codex-user-cache:v1",
        )

    def test_cache_clean_rejects_unknown_operations_without_runtime_effects(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        image_runtime = mock.Mock()
        with mock.patch(
                "host_pi_owner.detached_frontend",
                side_effect=AssertionError("cache cleanup detached")), \
                mock.patch.dict(launcher["main"].__globals__, {
                    "image_runtime": image_runtime,
                }), contextlib.redirect_stderr(io.StringIO()) as diagnostics:
            self.assertEqual(1, launcher["main"](["cache", "unknown"]))
        image_runtime.assert_not_called()
        self.assertIn("usage: codex-sandbox cache clean", diagnostics.getvalue())

    def test_restart_cli_rejects_invalid_arguments_before_stopping_sessions(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        restart = mock.Mock()
        invalid = [
            ["restart"], ["restart", "--repo"],
            ["restart", "--repo", str(self.repo), "extra"],
            ["restart", "--repo", str(self.root / "missing")],
            ["restart", "--repo", str(self.pi_marker)],
            ["restart-all", "--repo", str(self.repo)],
        ]
        with mock.patch("host_pi_owner.detached_frontend", side_effect=AssertionError("restart detached")), \
                mock.patch.dict(launcher["main"].__globals__, {
                    "restart_tmux_sessions": restart, "run": mock.Mock(),
                }), contextlib.redirect_stderr(io.StringIO()):
            for arguments in invalid:
                with self.subTest(arguments=arguments):
                    self.assertEqual(1, launcher["main"](arguments))
        restart.assert_not_called()

    def test_restart_registration_includes_the_launcher_process(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        registration = base64.urlsafe_b64encode(json.dumps({
            "version": 1, "pane": "%3", "repository": str(self.repo),
            "session": "session-id", "token": "token",
        }).encode()).decode()
        result = SimpleNamespace(stdout=f"0\t12345\t{registration}\n1\t\t{registration}\n")

        with mock.patch.dict(
            launcher["tmux_registrations"].__globals__,
            run=mock.Mock(return_value=result),
        ):
            self.assertEqual(
                [{
                    "version": 1, "pane": "%3", "dead": False, "pid": 12345,
                    "repository": str(self.repo), "session": "session-id",
                    "token": "token",
                }, {
                    "version": 1, "pane": "%3", "dead": True, "pid": None,
                    "repository": str(self.repo), "session": "session-id",
                    "token": "token",
                }],
                launcher["tmux_registrations"](),
            )

    def test_restart_registration_parser_rejects_invalid_sdk_locations(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        valid = self.restart_registration()
        valid = {key: value for key, value in valid.items() if key not in {"dead", "pid"}}
        for registration in ({**valid, "session": "relative.jsonl"}, {**valid, "cwd": "relative"},
                             {**valid, "repository": "relative"}, {**valid, "session": 42},
                             {**valid, "version": True}, {**valid, "extra": "not admitted"}):
            with self.subTest(registration=registration):
                encoded = base64.urlsafe_b64encode(json.dumps(registration).encode()).decode().rstrip("=")
                with mock.patch.dict(launcher["tmux_registrations"].__globals__,
                                     run=mock.Mock(return_value=SimpleNamespace(stdout=f"0\t12345\t{encoded}\n"))):
                    with self.assertRaisesRegex(launcher["LauncherError"], "invalid sandbox restart registration"):
                        launcher["tmux_registrations"]()

    def test_tmux_registration_declares_and_clears_pi_command(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(
            codex_arguments=["--session", "session-id"],
            repository=self.repo,
            host_working_directory=self.repo,
            tmux_pane=None,
            tmux_registration=None,
        )
        calls = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            stdout = state.tmux_registration or ""
            return subprocess.CompletedProcess(arguments, 0, stdout=stdout)

        function_globals = launcher["register_tmux_pane"].__globals__
        with mock.patch.dict(os.environ, {"TMUX_PANE": "%3"}), mock.patch.dict(
            function_globals, {"run": fake_run}
        ):
            launcher["register_tmux_pane"](state)
            launcher["unregister_tmux_pane"](state)

        self.assertTrue(any(
            call[:5] == ["tmux", "set-option", "-p", "-t", "%3"]
            and call[-7:] == [";", "set-option", "-p", "-t", "%3",
                              "@codex_sandbox_command", "π"]
            for call in calls
        ))
        self.assertIn(
            ["tmux", "set-option", "-p", "-u", "-t", "%3", "@codex_sandbox_command"],
            calls,
        )

    def test_sdk_registration_updates_preserve_generation_cleanup_ownership(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        for replaced in (False, True):
            with self.subTest(replaced=replaced):
                state = SimpleNamespace(codex_arguments=["--session", "launch-id"], repository=self.repo,
                                        host_working_directory=self.repo,
                                        tmux_pane=None, tmux_registration=None)
                current = ""
                calls = []

                def fake_run(arguments, **_kwargs):
                    calls.append(arguments)
                    return subprocess.CompletedProcess(arguments, 0, stdout=current)

                with mock.patch.dict(os.environ, {"TMUX_PANE": "%3"}), mock.patch.dict(
                    launcher["register_tmux_pane"].__globals__, run=fake_run,
                ):
                    launcher["register_tmux_pane"](state)
                    original = launcher["decode_tmux_registration"](state.tmux_registration)
                    updated = {**original, "version": 2, "cwd": str(self.repo),
                               "session": str(self.root / "actual-session.jsonl")}
                    if replaced:
                        updated["token"] = "another-generation"
                    current = base64.urlsafe_b64encode(json.dumps(updated).encode()).decode().rstrip("=")
                    calls.clear()
                    launcher["unregister_tmux_pane"](state)
                removals = [call for call in calls if call[:4] == ["tmux", "set-option", "-p", "-u"]]
                self.assertEqual(0 if replaced else 2, len(removals))


    def test_preserves_initial_working_directory_beneath_repository(self) -> None:
        playground = self.repo / "playground"
        playground.mkdir()
        result = self.run_launcher(cwd=playground)
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertEqual("/src/repository/playground", run[run.index("--workdir") + 1])

    def test_constructs_secured_agent_and_trusted_proxy_arguments(self) -> None:
        pi_agent = self.home / ".pi/agent"
        result = self.run_launcher("resume", "session-id")
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertIn("--cap-drop=NET_RAW", run)
        self.assertTrue((pi_agent / "sessions").is_dir())
        self.assertEqual(
            [f"type=bind,src={pi_agent / 'sessions'},"
             "dst=/home/codex/.pi/agent/sessions,readonly"],
            [argument for argument in run
             if "dst=/home/codex/.pi/agent/sessions" in argument],
        )
        self.assertNotIn("--cap-drop=ALL", run)
        self.assertNotIn("--security-opt=no-new-privileges", run)
        self.assertIn(f"type=bind,src={self.repo.resolve()},dst=/src/repository,bind-nonrecursive=true", run)
        self.assertIn(f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/repository/.git,readonly", run)
        self.assertIn(f"type=bind,src={(self.repo / '.jj').resolve()},dst=/src/repository/.jj,readonly", run)
        self.assertEqual(1, sum(argument.startswith("type=bind,") and "dst=/src,readonly" in argument for argument in run))
        self.assertEqual("/src/repository", run[run.index("--workdir") + 1])
        self.assertFalse(any("dst=/home/codex/.codex/" in argument for argument in run))
        self.assertNotIn(
            f"type=bind,src={pi_agent},dst=/home/codex/.pi/agent",
            run,
        )
        agent_mounts = [
            item for item in run
            if item.endswith("dst=/home/codex/.pi/agent")
        ]
        self.assertEqual(1, len(agent_mounts))
        private_agent = Path(agent_mounts[0].split(",src=", 1)[1].split(",dst=", 1)[0])
        self.assertFalse(private_agent.exists())
        staged_mounts = [
            item for item in run
            if any(item.endswith(f"dst={destination},readonly") for destination in (
                "/home/codex/.agents/shared.md",
                "/home/codex/.pi/agent/breq.md",
                "/home/codex/.pi/agent/settings.json",
                "/home/codex/.pi/agent/mcp.json",
                "/home/codex/.pi/agent/keybindings.json",
            ))
        ]
        self.assertEqual(5, len(staged_mounts))
        staged_sources = [
            Path(item.split(",src=", 1)[1].split(",dst=", 1)[0])
            for item in staged_mounts
        ]
        self.assertEqual(1, len({source.parent for source in staged_sources}))
        self.assertTrue(all(not source.is_relative_to(ROOT) for source in staged_sources))
        self.assertIn(
            f"type=bind,src={ROOT / 'config/pi-agent/pi-extensions'},"
            "dst=/home/codex/.pi/agent/pi-extensions,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'tools/pi-link'},"
            "dst=/home/codex/.pi/agent/pi-link,readonly",
            run,
        )
        self.assertNotIn("pi-agent-", " ".join(run))
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", run)
        self.assertIn("CODEX_SANDBOX_TOOL_WORKER=1", run)
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", run)
        self.assertNotIn("EDITOR=/opt/agent-tools/bin/host-editor", run)
        self.assertNotIn("VISUAL=/opt/agent-tools/bin/host-editor", run)
        self.assertFalse(any("dst=/run/host-editor" in item for item in run))

        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        self.assertEqual(1, len(snapshots))
        builder = snapshots[0][snapshots[0].index("--jj-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "jj-proxy-image", Path(builder).resolve())

    def test_enables_trusted_zulip_proxy_when_credentials_exist(self) -> None:
        zuliprc = self.home / ".zuliprc"
        zuliprc.write_text("[api]\nkey=secret\n", encoding="utf-8")
        zuliprc.chmod(0o600)
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        snapshot = snapshots[0]
        builder = snapshot[snapshot.index("--zulip-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "zulip-proxy-image", Path(builder).resolve())
        self.assertEqual(str(zuliprc), snapshot[snapshot.index("--zuliprc") + 1])
        attaches = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "attach"]
        self.assertEqual(str(zuliprc), attaches[0][attaches[0].index("--zuliprc") + 1])


    def test_retired_codex_login_reports_native_host_auth_without_launching(self) -> None:
        result = self.run_launcher("auth", "login")
        self.assertEqual(2, result.returncode)
        self.assertIn("use host Pi provider authentication", result.stderr)
        self.assertEqual([], read_calls(self.docker_log))
        self.assertFalse((self.home / ".codex-sandbox-auth").exists())

    def test_old_codex_credentials_never_create_or_enter_guest_broker(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        credential = auth / "auth.json"
        credential.write_text('{"tokens":{"access_token":"old-model-secret"}}')
        credential.chmod(0o600)
        for session in ("fresh", "shared"):
            with self.subTest(session=session):
                self.docker_log.unlink(missing_ok=True)
                self.python_log.unlink(missing_ok=True)
                result = self.run_launcher(FAKE_SESSION=session,
                    CODEX_SANDBOX_AUTH_DIR=str(auth), OPENAI_API_KEY="host-model-secret",
                    CODEX_SIDECAR_KEY="stale-model-session-token")
                self.assertEqual(0, result.returncode, result.stderr)
                calls = read_calls(self.docker_log)
                worker = self.final_run()
                for forbidden in ("CODEX_SIDECAR", "codex-sidecar", "codex-auth-proxy",
                                  "/var/lib/codex-auth", str(auth), "host-model-secret",
                                  "stale-model-session-token"):
                    self.assertNotIn(forbidden, "\n".join(worker))
                self.assertFalse(any("codex-auth-proxy" in item for call in calls for item in call))
                self.assertNotIn("--auth-enabled", self.python_log.read_text())
                self.assertEqual('{"tokens":{"access_token":"old-model-secret"}}', credential.read_text())

    def test_accepts_linked_git_worktree_metadata(self) -> None:
        shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").write_text("gitdir: ../main/.git/worktrees/repo\n", encoding="utf-8")
        git_dir = self.root / "main" / ".git" / "worktrees" / "repo"
        common_dir = self.root / "main" / ".git"
        git_dir.mkdir(parents=True)
        result = self.run_launcher(
            FAKE_GIT_DIR=str(git_dir), FAKE_GIT_COMMON_DIR=str(common_dir),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        repository = self.repo.resolve()
        git_mount = f"type=bind,src={self.repo / '.git'},dst=/src/repository/.git,readonly"
        self.assertIn(git_mount, run)
        self.assertEqual(1, run.count(git_mount))
        self.assertIn(
            f"type=bind,src={repository},dst={repository},readonly,bind-nonrecursive=true",
            run,
        )
        self.assertIn(
            f"type=bind,src={common_dir.resolve()},dst={common_dir.resolve()},readonly",
            run,
        )
        relative_target = Path(os.path.normpath(
            Path("/src/repository") / os.path.relpath(common_dir.resolve(), self.repo.resolve())
        ))
        self.assertIn(
            f"type=bind,src={common_dir.resolve()},dst={relative_target},readonly",
            run,
        )
        relative_repository = Path(os.path.normpath(
            relative_target / os.path.relpath(repository, common_dir.resolve())
        ))
        self.assertIn(
            f"type=bind,src={repository},dst={relative_repository},readonly,bind-nonrecursive=true",
            run,
        )
        self.assertNotIn(
            f"type=bind,src={git_dir.resolve()},dst={git_dir.resolve()},readonly",
            run,
        )

    def test_does_not_scan_trusted_host_metadata_for_hard_links(self) -> None:
        metadata = self.repo / ".jj" / "trusted-metadata"
        metadata.write_text("trusted", encoding="utf-8")
        os.link(metadata, self.repo / ".jj" / "trusted-metadata-link")
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_preserves_agent_exit_status_and_cleans_up(self) -> None:
        result = self.run_launcher(FAKE_AGENT_EXIT="23", CODEX_SANDBOX_TIMING="1")
        self.assertEqual(23, result.returncode, result.stderr)
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertRegex(docker_log, r"rm\t--force\tcodex-sandbox-[0-9]+-[0-9a-f]{12}")
        self.assertNotIn("codex-gateway-", docker_log)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertNotIn("hold-lock", actions)

    def test_timing_names_its_boundary_and_uses_the_full_cleanup_interval(self) -> None:
        builder = self.repo / ".agents" / "sandbox" / "base-image"
        builder.parent.mkdir(parents=True)
        write_executable(builder, "#!/bin/sh\nprintf '%s\\n' node:24-alpine3.22\n")
        result = self.run_launcher(
            CODEX_SANDBOX_TIMING="1", FAKE_CLEANUP_DELAY="0.2",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Sandbox preparation:", result.stderr)
        self.assertIn("base image resolution=", result.stderr)
        self.assertIn("tmux registration=", result.stderr)
        self.assertIn("service orchestration=", result.stderr)
        self.assertNotIn("Sandbox startup:", result.stderr)
        containers = float(re.search(
            r"Sandbox cleanup: containers=([0-9.]+)s", result.stderr,
        ).group(1))
        total = float(re.search(
            r"Sandbox cleanup total: ([0-9.]+)s", result.stderr,
        ).group(1))
        self.assertGreaterEqual(total, containers)

    def test_creates_network_with_public_only_routes(self) -> None:
        result = self.run_launcher(FAKE_NETWORK_EXISTS="0")
        self.assertEqual(0, result.returncode, result.stderr)
        creates = [
            call for call in read_calls(self.docker_log)
            if call[:2] == ["network", "create"] and call[-1] == "codex-public-only"
        ]
        self.assertEqual(1, len(creates))
        self.assertIn("--route", creates[0])
        self.assertIn("10.0.0.0/8,prohibit", creates[0])
        self.assertIn("192.168.0.0/16,prohibit", creates[0])

    def test_fresh_build_runs_agent_by_immutable_image_id(self) -> None:
        result = self.run_launcher(FAKE_IMAGE_EXISTS="0")
        self.assertEqual(0, result.returncode, result.stderr)
        builds = [call for call in read_calls(self.docker_log) if call[:1] == ["build"]]
        # Sidecar builds belong to sandbox-image; this launcher must use the
        # immutable result of its own freshly built agent image.
        agent_builds = [call for call in builds if any(
            argument.endswith("tools/codex-sandbox/image/Dockerfile") for argument in call)]
        self.assertEqual(1, len(agent_builds))
        self.assertIn('PI_REVISION=' + self.pi_revision, agent_builds[0])
        self.assertIn("sha256:" + "0" * 64, self.final_run())

    def test_shared_image_requires_the_installed_host_pi_revision(self) -> None:
        for revision in ('b' * 40, '', self.pi_revision):
            with self.subTest(revision=revision):
                self.docker_log.unlink(missing_ok=True)
                result = self.run_launcher(FAKE_SESSION='shared',
                                           FAKE_IMAGE_PI_REVISION=revision)
                if revision == self.pi_revision:
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.final_run()
                else:
                    self.assertEqual(1, result.returncode)
                    self.assertIn('Pi revision', result.stderr)
                    self.assertIn('codex-sandbox restart', result.stderr)
                    calls = read_calls(self.docker_log)
                    self.assertFalse(any(call[:1] == ['build'] for call in calls))
                    self.assertFalse(any('/opt/agent-tools/bin/tool-worker.mjs' in call
                                         for call in calls))

    def test_missing_host_revision_does_not_build_or_start_guest_worker(self) -> None:
        self.pi_marker.unlink()
        result = self.run_launcher(FAKE_IMAGE_EXISTS='0')
        self.assertEqual(1, result.returncode)
        self.assertIn('run mise run pi-install', result.stderr)
        calls = read_calls(self.docker_log)
        self.assertFalse(any(call[:1] == ['build'] and any(
            argument.endswith('tools/codex-sandbox/image/Dockerfile') for argument in call
        ) for call in calls))
        self.assertFalse(any('/opt/agent-tools/bin/tool-worker.mjs' in call for call in calls))

    def test_network_failure_stops_before_proxy_and_agent_start(self) -> None:
        result = self.run_launcher(FAKE_NETWORK_EXISTS="0", FAKE_NETWORK_CREATE_FAIL="1")
        self.assertEqual(1, result.returncode)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertNotIn("attach", actions)
        self.assertFalse(any(call[:1] == ["run"] for call in read_calls(self.docker_log)))

    def test_staging_ignores_dangling_skill_links(self) -> None:
        skills = self.home / ".agents" / "skills"
        (skills / "missing").symlink_to(self.root / "missing-skill", target_is_directory=True)
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.final_run()

    def test_term_signal_cleans_running_agent_and_proxies(self) -> None:
        ready = self.root / "agent-ready"
        process = subprocess.Popen(
            [sys.executable, str(LAUNCHER_FIXTURE)], cwd=self.repo,
            env=self.launcher_environment(FAKE_AGENT_BLOCK="1", FAKE_HOST_PI_READY=str(ready)),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.01)
        if not ready.exists():
            os.killpg(process.pid, signal.SIGTERM)
            self.fail(f"agent did not start: {process.communicate(timeout=5)!r}")
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(143, process.returncode, (stdout, stderr))
        docker_log = self.docker_log.read_text(encoding="utf-8")
        self.assertRegex(docker_log, r"rm\t--force\tcodex-sandbox-[0-9]+-[0-9a-f]{12}")
        self.assertNotIn("codex-gateway-", docker_log)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertNotIn("hold-lock", actions)

    def test_cli_literal_print_and_rpc_prompt_after_separator_still_holds_interactive_lease(self) -> None:
        ready = self.root / "literal-prompt-ready"
        result = self.run_launcher("--", "-p", "--mode", "rpc", FAKE_HOST_PI_READY=str(ready))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(ready.exists())
        self.assertIsInstance(json.loads(ready.read_text())["owner"], str)

    @unittest.skipUnless(NATIVE_TMUX, "native tmux unavailable")
    def test_cli_side_keeps_exact_worker_after_original_sigkill(self) -> None:
        server = "sandbox-cli-owner-" + uuid.uuid4().hex
        started = subprocess.run([NATIVE_TMUX, "-L", server, "new-session", "-d", "-P", "-F",
                                  "#{pane_id}", "sleep 60"], text=True, capture_output=True)
        if started.returncode:
            self.skipTest(started.stderr)
        pane = started.stdout.strip()
        tmux = subprocess.check_output([NATIVE_TMUX, "-L", server, "display-message", "-p",
                                        "#{socket_path},#{pid},0"], text=True).strip()
        ready = self.root / "actual-host-pi-ready"
        process = subprocess.Popen([sys.executable, str(LAUNCHER_FIXTURE)], cwd=self.repo,
            env=self.launcher_environment(FAKE_AGENT_BLOCK="1", FAKE_HOST_PI_READY=str(ready),
                                          TMUX=tmux, TMUX_PANE=pane),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

        def wait_for(predicate):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if predicate():
                    return
                time.sleep(.025)
            self.fail("native CLI controller condition did not become ready")

        def controller(info, value):
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(8)
                connection.connect(info["owner"])
                connection.sendall((json.dumps({"attachment": info["attachment"], **value}) + "\n").encode())
                with connection.makefile("rb") as stream:
                    return json.loads(stream.readline())

        try:
            wait_for(ready.exists)
            original = json.loads(ready.read_text())
            snapshot = self.root / "copied-session.jsonl"
            snapshot.write_text('{}\n')
            answer = controller(original, {"op": "side", "session": str(snapshot)})
            self.assertTrue(answer["ok"], answer)
            copied_ready = Path(str(snapshot) + ".fixture-ready")
            wait_for(copied_ready.exists)
            copied = json.loads(copied_ready.read_text())
            self.assertEqual(original["owner"], copied["owner"])
            self.assertEqual(original["container"], copied["container"])
            process.kill()
            process.wait(timeout=5)
            subprocess.run([NATIVE_TMUX, "-L", server, "kill-pane", "-t", pane], check=True)
            time.sleep(.2)
            removals = [call for call in read_calls(self.docker_log) if call[:1] == ["rm"]]
            self.assertFalse(any(original["container"] in call for call in removals))
            self.assertFalse(any(call[:2] == ["container", "ls"] for call in read_calls(self.docker_log)))
            self.assertTrue(controller(copied, {"op": "ready", "session": str(snapshot)})["ok"])
            Path(str(snapshot) + ".fixture-exit").touch()
            wait_for(lambda: not Path(original["owner"]).exists())
            self.assertEqual(1, len([call for call in read_calls(self.docker_log)
                                    if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]))
            removals = [call for call in read_calls(self.docker_log) if call[:1] == ["rm"]]
            self.assertTrue(any(original["container"] in call for call in removals))
            gateway_starts = [call for call in read_calls(self.docker_log)
                              if call[:2] == ["run", "--detach"] and
                              any(argument.startswith("codex-gateway-") for argument in call)]
            self.assertEqual([], gateway_starts)
        finally:
            subprocess.run([NATIVE_TMUX, "-L", server, "kill-server"], capture_output=True)
            if process.poll() is None:
                process.kill()
            process.wait()


    def test_agent_docker_relay_is_isolated_and_injected(self) -> None:
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        port = listener.getsockname()[1]
        access = self.root / "agent-docker"
        access.mkdir()
        (access / "connection.env").write_text(
            "AGENT_DOCKER_SSH_USER=worker\n"
            f"AGENT_DOCKER_SSH_PORT={port}\n"
            f"DOCKER_HOST=ssh://worker@host.docker.internal:{port}\n"
            "AGENT_DOCKER_SSHKEY=/run/secrets/agent-docker-key\n",
            encoding="utf-8",
        )
        (access / "id_ed25519").write_text("key", encoding="utf-8")
        (access / "known_hosts.sandbox").write_text("host", encoding="utf-8")
        result = self.run_launcher(
            AGENT_DOCKER_ACCESS_DIR=str(access), FAKE_RELAY_IP="10.0.0.8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        relay_runs = [
            call for call in calls
            if call[:2] == ["run", "--detach"]
            and any("codex-gateway-" in item for item in call)
        ]
        self.assertEqual(1, len(relay_runs))
        networks = [call for call in calls if call[:2] == ['network', 'create']
                    and any('codex-gateway-' in item for item in call)]
        self.assertEqual(len(networks), 2, 'Docker uses one private network pair')
        self.assertNotIn('--cpus', relay_runs[0], 'relay limits must not throttle Docker')
        self.assertIn('--build-port', relay_runs[0])
        self.assertFalse(any('agent-docker-key' in item or 'EDITOR_TOKEN' in item for item in relay_runs[0]))
        self.assertIn("--cap-drop=ALL", relay_runs[0])
        self.assertIn("--read-only", relay_runs[0])
        self.assertEqual(
            "sha256:" + "0" * 64,
            relay_runs[0][relay_runs[0].index("/trusted/bin/sandbox-gateway") + 1],
        )
        run = self.final_run()
        relay_name = relay_runs[0][relay_runs[0].index("--name") + 1]
        self.assertIn(f"DOCKER_HOST=ssh://worker@{relay_name}:2222", run)
        self.assertIn(
            f"type=bind,src={access / 'id_ed25519'},dst=/run/secrets/agent-docker-key,readonly",
            run,
        )

    def test_rejects_incomplete_agent_docker_configuration(self) -> None:
        access = self.root / "agent-docker"
        access.mkdir()
        (access / "connection.env").write_text("DOCKER_HOST=x\n", encoding="utf-8")
        result = self.run_launcher(AGENT_DOCKER_ACCESS_DIR=str(access))
        self.assertEqual(1, result.returncode)
        self.assertIn("Agent Docker access state is incomplete", result.stderr)
        self.assertEqual([], read_calls(self.docker_log))


if __name__ == "__main__":
    unittest.main()
