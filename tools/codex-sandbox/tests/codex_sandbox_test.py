from __future__ import annotations

import base64
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
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "codex-sandbox"
LAUNCHER = TOOL / "codex-sandbox"
LAUNCHER_FIXTURE = TOOL / "tests" / "launcher_fixture.py"
AGENT_WRAPPERS_PROFILE = TOOL / "image" / "agent-wrappers-path.sh"
DOTFILES_PROFILE = TOOL / "image" / "dotfiles-profile.sh"
SANDBOX_GITCONFIG = TOOL / "image" / "gitconfig"
SANDBOX_DOCKERFILE = TOOL / "image" / "Dockerfile"
HOST_EDITOR_CLIENT = TOOL / "image" / "host-editor"
HOST_EDITOR_PANE = TOOL / "host-editor-pane"


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o700)


def read_calls(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [line.split("\t")[1:] for line in path.read_text(encoding="utf-8").splitlines()]


class ContainerRepositoryPathTest(unittest.TestCase):
    def test_only_first_session_publishes_shared_proxy_state(self):
        launcher = runpy.run_path(str(LAUNCHER))
        finalize = launcher['finalize_proxy_session']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready, output = root / 'ready', root / 'args'
            state = SimpleNamespace(lock_ready=ready, repository=root,
                                    container_repository=Path('/src/repo'),
                                    proxy_state=root / 'state', manifest=root / 'manifest')
            def helper(operation, *arguments):
                output.write_text('--read-only\n')
            for status, operation in (('shared', 'agent-args'), ('new', 'finalize')):
                with self.subTest(status=status):
                    ready.write_text(status + '\n')
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
            self.assertEqual(0, launcher["main"]([]))
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
                metadata_roots=(), skills_tmp=repository, zuliprc=None, agent_podman=None)
            backend = mock.Mock()
            with mock.patch.dict(launcher["preflight_lima"].__globals__, OUTER_RUNTIME=backend,
                                 _secure_codex_auth_directory=lambda _: None):
                with self.assertRaisesRegex(launcher["LauncherError"], "whole home"):
                    launcher["preflight_lima"](state)
            backend.host.check_bind.assert_not_called()
            backend.host.check_binds.assert_not_called()

    def test_lima_preflight_submits_all_mount_permissions_in_one_batch(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repository = home / "src/project"
            repository.mkdir(parents=True)
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").touch()
            state = SimpleNamespace(home=home, repository=repository, skills_source=repository,
                metadata_roots=(), skills_tmp=repository, zuliprc=None, agent_podman=None)
            backend = mock.Mock()
            with mock.patch.dict(launcher["preflight_lima"].__globals__, OUTER_RUNTIME=backend,
                                 _secure_codex_auth_directory=lambda _: None):
                launcher["preflight_lima"](state)
            backend.host.check_bind.assert_not_called()
            backend.host.check_binds.assert_called_once()
            sources = backend.host.check_binds.call_args.args[0]
            self.assertIn((repository, True), sources)
            self.assertIn((repository, False), sources)
            self.assertIn((home / ".codex/config.toml", False), sources)
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


class ProxyHelperTest(unittest.TestCase):
    def test_short_calls_do_not_spawn_an_interpreter_and_preserve_failure(self) -> None:
        helper = runpy.run_path(str(LAUNCHER))["helper"]
        entrypoint = mock.Mock(return_value=0)
        with mock.patch.dict(helper.__globals__, proxy_module=lambda: SimpleNamespace(main=entrypoint)), \
                mock.patch("subprocess.run", side_effect=AssertionError("unexpected process")):
            self.assertEqual(0, helper("snapshot", "--repo", "example").returncode)
            entrypoint.assert_called_once_with(["snapshot", "--repo", "example"])
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


class BackgroundRelayTest(unittest.TestCase):
    def test_docker_startup_uses_existing_image_builders(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))['execute']
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            builder = repository / '.agents/sandbox/base-image'
            builder.parent.mkdir(parents=True)
            builder.touch(mode=0o755)
            manifest = repository / 'manifest.json'
            manifest.write_text('{"commands": {}}')
            state = SimpleNamespace(repository=repository, agent_podman=None,
                                    codex_arguments=[], deferred_signal=None, manifest=manifest)
            replacements = {name: mock.Mock(return_value=[]) for name in (
                'validate_repository', 'stage_skills', 'register_tmux_pane', 'ensure_network',
                'acquire_lock', 'prepare_editor_relay', 'start_editor_relay', 'attach_proxies')}
            replacements.update(OUTER_RUNTIME=SimpleNamespace(provider='lima-docker'),
                proxy_module=lambda: SimpleNamespace(resolve_images=mock.Mock(return_value={})),
                temporary_file=lambda: repository / 'images.json',
                ensure_image=mock.Mock(return_value='agent@digest'),
                resolve_sidecar_image=mock.Mock(return_value='auth@digest'),
                run=mock.Mock(return_value=SimpleNamespace(stdout='base@digest')),
                run_agent=mock.Mock(return_value=0))
            with mock.patch.dict(execute.__globals__, replacements):
                self.assertEqual(0, execute(state))
                replacements['ensure_image'].assert_called_once_with(state, 'base@digest')
                replacements['resolve_sidecar_image'].assert_called_once()
                self.assertIn('agent@digest', replacements['run_agent'].call_args.args[1])
                replacements['ensure_image'].side_effect = ValueError('build failed')
                replacements['run_agent'].reset_mock()
                with self.assertRaisesRegex(ValueError, 'build failed'):
                    execute(state)
                replacements['run_agent'].assert_not_called()

    def test_agent_wait_rejects_supervisor_loss_during_startup(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        agent = mock.Mock()
        agent.wait.side_effect = subprocess.TimeoutExpired("owned-agent", 0.1)
        monitor = mock.Mock()
        monitor.poll.return_value = -9
        with self.assertRaisesRegex(launcher["LauncherError"], "supervision failed"):
            launcher["wait_for_monitored_agent"](SimpleNamespace(agent_process=agent, monitor_process=monitor))

    def test_signal_during_image_build_waits_before_proxy_cleanup(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        main = launcher["main"]
        build_release = threading.Event()
        build_finished = threading.Event()
        proxy_attached = threading.Event()

        with tempfile.TemporaryDirectory() as directory:
            state = SimpleNamespace(
                repository=Path(directory), agent_podman=None, codex_arguments=[],
                joining_workers=False, deferred_signal=None,
            )

            def ensure_image(_state, _base_image):
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
                    "acquire_lock", "prepare_editor_relay", "stage_skills",
                )
            }
            replacements.update(
                ensure_image=ensure_image,
                resolve_sidecar_image=mock.Mock(return_value="sidecar"),
                attach_proxies=attach_proxies,
                run=mock.Mock(return_value=SimpleNamespace(stdout="Darwin")),
                start_editor_relay=mock.Mock(),
                run_agent=mock.Mock(side_effect=AssertionError("agent must not start")),
            )

            interrupter = threading.Thread(target=interrupt_after_proxy_attachment)

            def cleanup(_state):
                self.assertTrue(build_finished.is_set(), "cleanup raced the image build")

            with mock.patch.dict(
                main.__globals__,
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
        main = launcher["main"]
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

        with mock.patch.dict(main.__globals__, new_state=lambda _: state,
                             execute=execute, cleanup=cleanup,
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
            state = SimpleNamespace(repository=Path(directory), agent_podman={}, codex_arguments=[],
                                    deferred_signal=None)
            replacements = {
                name: mock.Mock(return_value=[])
                for name in ("validate_repository", "register_tmux_pane", "ensure_network",
                             "acquire_lock", "attach_proxies", "prepare_editor_relay",
                             "prepare_relay", "stage_skills")
            }
            replacements.update(
                ensure_image=mock.Mock(return_value="image"),
                resolve_sidecar_image=mock.Mock(return_value="sidecar"),
                run=mock.Mock(return_value=SimpleNamespace(stdout="Darwin")),
                start_editor_relay=relay, start_relay=relay, run_agent=agent,
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
                self.assertEqual(2, output.getvalue().count("injected optional failure"))


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

    def test_image_installs_host_editor_client(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "COPY --chmod=755 ./tools/codex-sandbox/image/host-editor "
            "/opt/agent-tools/bin/host-editor",
            dockerfile,
        )
        self.assertIn("ENV EDITOR=vi VISUAL=vi", dockerfile)

    def test_woodpecker_adapter_remains_visible_after_bb_resolves_its_wrapper(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "COPY --chown=${AGENT_UID}:${AGENT_GID} "
            "./tools/agent-podman/woodpecker-cli "
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
            "/libexec/agent-wrappers:/usr/local/bin:/usr/bin:/bin\n",
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
            "/libexec/agent-wrappers:/opt/agent-tools/bin:/opt/agent-pi/bin:"
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


class HostEditorPaneTest(unittest.TestCase):
    def test_runs_editor_argv_and_records_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            editor = root / "editor"
            write_executable(editor, """
                #!/bin/sh
                printf '%s\\n' "$2" > "$1"
                exit 7
            """)
            output = root / "output"
            status = root / "status"

            result = subprocess.run([
                str(HOST_EDITOR_PANE), str(status), "--",
                str(editor), str(output), "value with spaces",
            ])

            self.assertEqual(7, result.returncode)
            self.assertEqual("7\n", status.read_text(encoding="utf-8"))
            self.assertEqual("value with spaces\n", output.read_text(encoding="utf-8"))


class HostEditorBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = runpy.run_path(str(LAUNCHER))
        self.bridge = self.launcher["HostEditorBridge"]()

    def tearDown(self) -> None:
        self.bridge.stop()

    def start_bridge(self) -> None:
        self.bridge.start()
        self.bridge.allow_peers({"127.0.0.1"})

    def run_client(
        self, content: str, *, token: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "prompt.md"
            document.write_text(content, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HOST_EDITOR_CLIENT), str(document)],
                env={
                    **os.environ,
                    "CODEX_SANDBOX_EDITOR_ADDRESS": f"127.0.0.1:{self.bridge.port}",
                    "CODEX_SANDBOX_EDITOR_TOKEN": token or self.bridge.token,
                },
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            )
            return result, document.read_text(encoding="utf-8")

    def test_guest_client_round_trips_only_document_text(self) -> None:
        self.bridge._edit = lambda content: content + " edited"
        self.start_bridge()

        result, content = self.run_client("draft")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("draft edited", content)

    def test_guest_client_preserves_document_when_host_editor_fails(self) -> None:
        def fail(_content: str) -> str:
            raise self.launcher["LauncherError"]("editor refused")

        self.bridge._edit = fail
        self.start_bridge()

        result, content = self.run_client("draft")

        self.assertEqual(1, result.returncode)
        self.assertIn("editor refused", result.stderr)
        self.assertEqual("draft", content)

    def test_client_rejects_linked_files_before_contacting_host(self) -> None:
        self.start_bridge()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("draft", encoding="utf-8")
            link = root / "link"
            link.symlink_to(target)
            result = subprocess.run(
                [sys.executable, str(HOST_EDITOR_CLIENT), str(link)],
                env={
                    **os.environ,
                    "CODEX_SANDBOX_EDITOR_ADDRESS": f"127.0.0.1:{self.bridge.port}",
                    "CODEX_SANDBOX_EDITOR_TOKEN": self.bridge.token,
                },
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("unlinked regular file", result.stderr)

    def test_unapproved_network_peer_is_closed_immediately(self) -> None:
        self.bridge.start()
        connection = socket.create_connection(("127.0.0.1", self.bridge.port), timeout=1)
        connection.sendall(b"\x00\x00")

        try:
            self.assertEqual(b"", connection.recv(1))
        except ConnectionResetError:
            pass
        connection.close()

    def test_wrong_session_token_cannot_open_host_editor(self) -> None:
        self.bridge._edit = mock.Mock(return_value="changed")
        self.start_bridge()

        result, content = self.run_client("draft", token="wrong")

        self.assertEqual(1, result.returncode)
        self.assertIn("invalid host editor request", result.stderr)
        self.assertEqual("draft", content)
        self.bridge._edit.assert_not_called()

    def test_partial_request_does_not_wedge_later_edits(self) -> None:
        self.bridge._edit = lambda content: content + " edited"
        self.bridge._serve.__globals__["EDITOR_REQUEST_TIMEOUT_SECONDS"] = 0.1
        self.start_bridge()
        stalled = socket.create_connection(("127.0.0.1", self.bridge.port), timeout=1)
        stalled.sendall(b"\x00\x00")
        time.sleep(0.2)

        result, content = self.run_client("draft")

        stalled.close()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("draft edited", content)

    def test_stop_closes_listener(self) -> None:
        self.start_bridge()
        port = self.bridge.port
        self.bridge.stop()

        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.1)


class CodexSandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "repo with spaces"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".jj" / "repo").mkdir(parents=True)
        self.home = self.root / "home with spaces"
        (self.home / ".agents" / "skills").mkdir(parents=True)
        (self.home / ".codex" / "rules").mkdir(parents=True)
        (self.home / "src").mkdir()
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.docker_log = self.root / "docker.log"
        self.python_log = self.root / "python.log"
        self.codex_log = self.root / "codex.log"
        self.jj_log = self.root / "jj.log"

        write_executable(self.fake_bin / "codex", """
            #!/bin/sh
            printf '%s\t%s\n' "$CODEX_HOME" "$*" > "$FAKE_CODEX_LOG"
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
            [ "$1 $2" = "workspace root" ] || exit 2
            [ -d "$FAKE_REPOSITORY/.jj" ] || exit 1
            printf '%s\n' "$FAKE_REPOSITORY"
        """)
        write_executable(self.fake_bin / "git", """
            #!/bin/sh
            case " $* " in
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
            if [ "$1 $2" = "network inspect" ]; then
                printf '%s\n' 127.0.0.1
                exit
            fi
            if [ "$1 $2" = "image inspect" ]; then
                for image do :; done
                if [ "${FAKE_IMAGE_EXISTS:-1}" != 1 ] && [ ! -f "$FAKE_DOCKER_LOG.$image" ]; then
                    exit 1
                fi
                case " $* " in
                    *" --format "*) printf 'sha256:%064d\n' 0; exit 0 ;;
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
            if [ "$1" = exec ] && [ "${FAKE_EDITOR_UNREACHABLE:-0}" = 1 ]; then
                case "$2" in codex-host-editor-relay-*) exit 79 ;; esac
            fi
            exit 0
        """)
        write_executable(self.fake_bin / "python3", """
            #!/bin/sh
            # Repository builders now use the image helper's single-reference
            # protocol. Keep the launch test independent of a real image build.
            case "$1" in
                */sandbox-image) printf 'sha256:%064d\\n' 0; exit 0 ;;
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
                    printf '%s\n' '{"version":1,"commands":{"jj":{}}}' > "$output"
                    ;;
                hold-lock)
                    ready=$(value_for --ready "$@")
                    coordinated=$(value_for --coordinated "$@")
                    release=$(value_for --release "$@")
                    printf '%s\n' "${FAKE_SESSION:-new}" > "$ready"
                    while [ ! -e "$coordinated" ]; do sleep 0.01; done
                    while [ ! -e "$release" ]; do sleep 0.01; done
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
                publish|monitor) ;;
                *) exit 91 ;;
            esac
        """)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def launcher_environment(self, **updates: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("TMUX", None)
        environment.update({
            "PATH": f"{self.fake_bin}:{environment['PATH']}",
            "HOME": str(self.home),
            "FAKE_REPOSITORY": str(self.repo),
            "FAKE_DOCKER_LOG": str(self.docker_log),
            "FAKE_PYTHON_LOG": str(self.python_log),
            "FAKE_CODEX_LOG": str(self.codex_log),
            "FAKE_JJ_LOG": str(self.jj_log),
            "AGENT_PODMAN_ACCESS_DIR": str(self.root / "no-agent-podman"),
            "FAKE_NETWORK_EXISTS": "1",
            "FAKE_UNAME": "Linux",
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
        runs = [call for call in read_calls(self.docker_log) if call[:1] == ["run"] and "-it" in call]
        self.assertEqual(1, len(runs))
        return runs[0]

    def test_mounts_host_skills_writable_through_resolved_source(self) -> None:
        skills = self.home / ".agents" / "skills"
        skills.rmdir()
        source = self.root / "tracked-skills"
        source.mkdir()
        skills.symlink_to(source, target_is_directory=True)

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

    def test_loads_repository_and_home_sandbox_instructions(self) -> None:
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
            agents = (state.skills_tmp / "config/pi-AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(
                "@breq.md\n"
                "@coordination-dialect.md\n"
                "@../../.agents/shared.md\n"
                "@/src/repository/.agents/sandbox/AGENTS.md\n"
                "@../../.agents/sandbox/AGENTS.md\n",
                agents,
            )
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

    def test_staged_settings_scope_external_editor_to_the_sandbox(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            settings = json.loads(
                (state.skills_tmp / "config/pi.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "/opt/agent-tools/bin/host-editor", settings["externalEditor"]
            )
            source = json.loads((ROOT / "config/pi.json").read_text(encoding="utf-8"))
            self.assertNotIn("externalEditor", source)
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

    def test_mounts_subagent_configuration_from_staged_dotfiles(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            launcher["stage_skills"](state)
            staged = state.skills_tmp / "config/pi-codex-subagents.json"
            self.assertEqual(
                json.loads((ROOT / "config/pi-codex-subagents.json").read_text(encoding="utf-8")),
                json.loads(staged.read_text(encoding="utf-8")),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(
            item.endswith(
                "/config/pi-codex-subagents.json,dst=/home/codex/.pi/agent/"
                "pi-codex-subagents/config.json,readonly"
            )
            for item in self.final_run()
        ))

    def test_launch_initializes_a_missing_jj_repository(self) -> None:
        shutil.rmtree(self.repo / ".jj")
        shutil.rmtree(self.repo / ".git")

        result = self.run_launcher()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.repo / ".jj" / "repo").is_dir())
        self.assertTrue((self.repo / ".git").is_dir())
        self.final_run()

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

    def test_restart_all_stops_resets_and_relaunches_registered_panes(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        registrations = [{
            "version": 1, "pane": "%3", "dead": False, "pid": 12345,
            "repository": str(self.repo), "session": "session-id", "token": "token",
        }]
        calls = []
        resets = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            return SimpleNamespace(stdout="off\n")

        function_globals = launcher["restart_all_tmux_sessions"].__globals__
        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            function_globals, {
                "tmux_registrations": mock.Mock(side_effect=[registrations, []]),
                "run": fake_run,
                "helper": lambda *arguments: resets.append(arguments),
            },
        ), mock.patch.object(os, "kill") as kill:
            self.assertEqual(0, launcher["restart_all_tmux_sessions"]())
        kill.assert_called_once_with(12345, signal.SIGTERM)
        self.assertEqual([("reset", "--repo", str(self.repo))], resets)
        self.assertIn(
            ["tmux", "set-option", "-p", "-t", "%3", "remain-on-exit", "on"],
            calls,
        )
        respawn = next(call for call in calls if call[:2] == ["tmux", "respawn-pane"])
        self.assertEqual(
            f"cd {shlex.quote(str(self.repo))} && pi --session session-id",
            respawn[-1],
        )
        self.assertIn(
            ["tmux", "set-option", "-p", "-t", "%3", "remain-on-exit", "off"],
            calls,
        )
        self.assertFalse(any(call[-1:] in (["C-c"], ["Enter"]) for call in calls))
        self.assertTrue(any(call[:2] == ["tmux", "display-message"] for call in calls))

    def test_restart_all_respawns_an_already_dead_registered_pane(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        registrations = [{
            "version": 1, "pane": "%3", "dead": True, "pid": None,
            "repository": str(self.repo), "session": "session-id", "token": "token",
        }]
        calls = []

        def fake_run(arguments, **_kwargs):
            calls.append(arguments)
            return SimpleNamespace(stdout="off\n")

        with mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux"}), mock.patch.dict(
            launcher["restart_all_tmux_sessions"].__globals__, {
                "tmux_registrations": mock.Mock(side_effect=[registrations, registrations]),
                "run": fake_run,
                "helper": mock.Mock(),
            },
        ), mock.patch.object(os, "kill") as kill:
            self.assertEqual(0, launcher["restart_all_tmux_sessions"]())

        kill.assert_not_called()
        self.assertTrue(any(call[:2] == ["tmux", "respawn-pane"] for call in calls))

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

    def test_tmux_registration_declares_and_clears_pi_command(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        state = SimpleNamespace(
            codex_arguments=["--session", "session-id"],
            repository=self.repo,
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

        self.assertIn(
            ["tmux", "set-option", "-p", "-t", "%3", "@codex_sandbox_command", "π"],
            calls,
        )
        self.assertIn(
            ["tmux", "set-option", "-p", "-u", "-t", "%3", "@codex_sandbox_command"],
            calls,
        )

    def test_browser_oauth_login_uses_dedicated_codex_home(self) -> None:
        result = self.run_launcher("auth", "login")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.home / '.codex-sandbox-auth'}\tlogin\n",
            self.codex_log.read_text(encoding="utf-8"),
        )
        self.assertEqual(0o700, (self.home / ".codex-sandbox-auth").stat().st_mode & 0o777)
        self.assertEqual([], read_calls(self.docker_log))

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
        self.assertIn("--cap-drop=ALL", run)
        self.assertIn("--security-opt=no-new-privileges", run)
        self.assertIn(f"type=bind,src={self.repo.resolve()},dst=/src/repository,bind-nonrecursive=true", run)
        self.assertIn(f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/repository/.git,readonly", run)
        self.assertIn(f"type=bind,src={(self.repo / '.jj').resolve()},dst=/src/repository/.jj,readonly", run)
        self.assertEqual("/src/repository", run[run.index("--workdir") + 1])
        self.assertIn(
            f"type=bind,src={ROOT / 'config/codex.toml'},"
            "dst=/home/codex/.codex/dotfiles.config.toml,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'config/codex-developer-instructions.md'},"
            "dst=/home/codex/.codex/developer-instructions.md,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'config/breq.md'},"
            "dst=/home/codex/.codex/breq.md,readonly",
            run,
        )
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
        self.assertIn(
            f"type=bind,src={pi_agent / 'sessions'},dst=/home/codex/.pi/agent/sessions",
            run,
        )
        for directory in ("npm", "git"):
            package_store = pi_agent / directory
            self.assertTrue(package_store.is_dir())
            self.assertIn(
                f"type=bind,src={package_store},"
                f"dst=/home/codex/.pi/agent/{directory}",
                run,
            )
            self.assertNotIn(
                f"type=bind,src={package_store},"
                f"dst=/home/codex/.pi/agent/{directory},readonly",
                run,
            )
        auth_mounts = [
            item for item in run
            if item.endswith("dst=/home/codex/.pi/agent/auth.json,readonly")
        ]
        self.assertEqual(1, len(auth_mounts))
        auth_mask = Path(auth_mounts[0].split(",src=", 1)[1].split(",dst=", 1)[0])
        self.assertFalse(auth_mask.exists())
        staged_mounts = [
            item for item in run
            if any(item.endswith(f"dst={destination},readonly") for destination in (
                "/home/codex/.agents/shared.md",
                "/home/codex/.agents/coordination-dialect.md",
                "/home/codex/.pi/agent/AGENTS.md",
                "/home/codex/.pi/agent/breq.md",
                "/home/codex/.pi/agent/coordination-dialect.md",
                "/home/codex/.pi/agent/settings.json",
                "/home/codex/.pi/agent/mcp.json",
                "/home/codex/.pi/agent/keybindings.json",
            ))
        ]
        self.assertEqual(8, len(staged_mounts))
        staged_sources = [
            Path(item.split(",src=", 1)[1].split(",dst=", 1)[0])
            for item in staged_mounts
        ]
        self.assertEqual(1, len({source.parent for source in staged_sources}))
        self.assertTrue(all(not source.is_relative_to(ROOT) for source in staged_sources))
        self.assertIn(
            f"type=bind,src={ROOT / 'config/pi-extensions'},"
            "dst=/home/codex/.pi/agent/pi-extensions,readonly",
            run,
        )
        self.assertNotIn("pi-agent-", " ".join(run))
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", run)
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", run)
        self.assertNotIn("EDITOR=/opt/agent-tools/bin/host-editor", run)
        self.assertNotIn("VISUAL=/opt/agent-tools/bin/host-editor", run)
        self.assertTrue(any(item.startswith("CODEX_SANDBOX_EDITOR_ADDRESS=") for item in run))
        self.assertIn("CODEX_SANDBOX_EDITOR_TOKEN", run)
        self.assertFalse(any(item.startswith("CODEX_SANDBOX_EDITOR_TOKEN=") for item in run))
        self.assertFalse(any("dst=/run/host-editor" in item for item in run))
        self.assertLess(run.index("resume"), run.index("session-id"))

        snapshots = [call for call in read_calls(self.python_log) if len(call) > 1 and call[1] == "snapshot"]
        self.assertEqual(1, len(snapshots))
        builder = snapshots[0][snapshots[0].index("--jj-image-command") + 1]
        self.assertEqual(ROOT / ".agents" / "sandbox" / "jj-proxy-image", Path(builder).resolve())

    def test_seeds_offline_model_catalog_without_sharing_guest_writes(self) -> None:
        catalog = self.home / ".pi/agent/models-store.json"
        catalog.parent.mkdir(parents=True)
        contents = '{"openai-codex":{"models":[{"id":"gpt-6-astra"}]}}\n'
        catalog.write_text(contents, encoding="utf-8")
        captured = self.root / "guest-models.json"

        result = self.run_launcher(FAKE_MODEL_STORE_CAPTURE=str(captured))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(contents, captured.read_text(encoding="utf-8"))
        self.assertEqual(contents, catalog.read_text(encoding="utf-8"))

    def test_model_catalog_copy_failure_stops_agent_launch(self) -> None:
        (self.home / ".pi/agent/models-store.json").mkdir(parents=True)

        result = self.run_launcher()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("models-store.json", result.stderr)
        self.assertFalse(any("-it" in call for call in read_calls(self.docker_log)))

    def test_rejects_symlinked_persistent_pi_sessions(self) -> None:
        pi_agent = self.home / ".pi/agent"
        pi_agent.mkdir(parents=True)
        target = self.root / "foreign-sessions"
        target.mkdir()
        (pi_agent / "sessions").symlink_to(target, target_is_directory=True)

        result = self.run_launcher("resume", "session-id")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Pi sessions directory is invalid", result.stderr)

    def test_rejects_symlinked_persistent_pi_package_store(self) -> None:
        pi_agent = self.home / ".pi/agent"
        pi_agent.mkdir(parents=True)
        target = self.root / "foreign-packages"
        target.mkdir()
        (pi_agent / "npm").symlink_to(target, target_is_directory=True)

        result = self.run_launcher("resume", "session-id")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Pi package directory is invalid", result.stderr)

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

    def test_starts_codex_auth_sidecar_without_mounting_auth_in_agent(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text(
            '{"tokens":{"access_token":"a","refresh_token":"r"}}\n', encoding="utf-8",
        )
        (auth / "auth.json").chmod(0o600)

        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        sidecars = [
            call for call in calls
            if call[:2] == ["run", "--detach"] and any("codex-auth-proxy-" in item for item in call)
        ]
        self.assertEqual(1, len(sidecars))
        sidecar = sidecars[0]
        self.assertIn(
            f"type=bind,src={auth.resolve()},dst=/var/lib/codex-auth", sidecar,
        )
        self.assertIn("--read-only", sidecar)
        self.assertEqual("sha256:" + "0" * 64, sidecar[-1])
        sidecar_name = sidecar[sidecar.index("--name") + 1]
        readiness = [call for call in calls if call[:3] == [
            "exec", sidecar_name, "/usr/local/bin/python3",
        ]]
        self.assertEqual(1, len(readiness))
        agent = self.final_run()
        self.assertFalse(any(str(auth) in item for item in agent))
        self.assertTrue(any(item.startswith("CODEX_SIDECAR_URL=http://codex-auth-proxy-") for item in agent))
        self.assertIn(
            f"type=bind,src={ROOT / 'tools/codex-sandbox/auth-proxy/pi-extension'},"
            "dst=/home/codex/.pi/agent/extensions/codex-sidecar,readonly",
            agent,
        )

    def test_reuses_auth_sidecar_from_persistent_proxy_session(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text(
            '{"tokens":{"access_token":"a","refresh_token":"r"}}\n', encoding="utf-8",
        )
        (auth / "auth.json").chmod(0o600)

        result = self.run_launcher(
            FAKE_SESSION="shared",
            FAKE_PROXY_STATE=(
                '{"proxies":[],"auth":{"container":"shared-auth-proxy",'
                '"key":"shared-key","image":"sha256:' + '0' * 64 + '"}}'
            ),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        self.assertFalse(any(
            call[:2] == ["run", "--detach"] and "shared-auth-proxy" in call
            for call in calls
        ))
        agent = self.final_run()
        self.assertIn("CODEX_SIDECAR_URL=http://shared-auth-proxy:8787", agent)
        self.assertIn("CODEX_SIDECAR_KEY=shared-key", agent)

    def test_rejects_cached_auth_sidecar_from_another_network(self) -> None:
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text(
            '{"tokens":{"access_token":"a","refresh_token":"r"}}\n', encoding="utf-8",
        )
        (auth / "auth.json").chmod(0o600)

        result = self.run_launcher(
            FAKE_SESSION="shared",
            FAKE_SIDECAR_NETWORK="0",
            FAKE_PROXY_STATE=(
                '{"proxies":[],"auth":{"container":"stale-auth-proxy",'
                '"key":"stale-key","image":"sha256:' + '0' * 64 + '"}}'
            ),
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("belongs to another sandbox network", result.stderr)
        calls = read_calls(self.docker_log)
        self.assertFalse(any(call[:1] == ["run"] and "-it" in call for call in calls))
        self.assertTrue(any(
            call[:2] == ["rm", "--force"]
            and any("codex-host-editor-relay-" in item for item in call)
            for call in calls
        ))

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
        self.assertIn(
            f"type=bind,src={(self.repo / '.git').resolve()},dst=/src/repository/.git,readonly",
            run,
        )
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
        self.assertIn("codex-host-editor-relay-", docker_log)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertIn("hold-lock", actions)

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
        self.assertTrue(any("tools/codex-sandbox/image/Dockerfile" in call for call in builds))
        self.assertIn("sha256:built-image-id", self.final_run())

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
            env=self.launcher_environment(FAKE_AGENT_BLOCK="1", FAKE_AGENT_READY=str(ready)),
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
        self.assertIn("codex-host-editor-relay-", docker_log)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertIn("hold-lock", actions)

    def test_non_linux_omits_native_linux_restrictions(self) -> None:
        result = self.run_launcher(FAKE_UNAME="Darwin")
        self.assertEqual(0, result.returncode, result.stderr)
        run = self.final_run()
        self.assertNotIn("--cap-drop=ALL", run)
        self.assertIn("--cap-drop=NET_RAW", run)
        self.assertNotIn("--security-opt=no-new-privileges", run)
        self.assertNotIn("native Linux sandboxing", result.stderr)

    def test_host_editor_relay_is_isolated_and_injected(self) -> None:
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        relay = next(
            call for call in calls
            if call[:2] == ["run", "--detach"]
            and any("codex-host-editor-relay-" in item for item in call)
        )
        self.assertIn("--cap-drop=ALL", relay)
        self.assertIn("--security-opt=no-new-privileges", relay)
        self.assertIn("--read-only", relay)
        self.assertIn("--pids-limit", relay)
        self.assertIn("--memory", relay)
        self.assertIn("--cpus", relay)
        self.assertIn("--http-proxy=false", relay)
        self.assertIn("/usr/bin/socat", relay)
        editor_networks = [
            call for call in calls if call[:2] == ["network", "create"]
            and any("codex-host-editor-" in item for item in call)
        ]
        self.assertEqual(2, len(editor_networks))
        self.assertTrue(any("--internal" in call for call in editor_networks))
        run = self.final_run()
        self.assertTrue(any(item.startswith("CODEX_SANDBOX_EDITOR_ADDRESS=") for item in run))
        self.assertIn("CODEX_SANDBOX_EDITOR_TOKEN", run)
        self.assertFalse(any(item.startswith("CODEX_SANDBOX_EDITOR_TOKEN=") for item in run))

    def test_unreachable_editor_does_not_prevent_agent_startup(self) -> None:
        result = self.run_launcher(FAKE_EDITOR_UNREACHABLE="1")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CODEX_SANDBOX_EDITOR_TOKEN", self.final_run())

    def test_agent_podman_relay_is_isolated_and_injected(self) -> None:
        access = self.root / "agent-podman"
        access.mkdir()
        (access / "connection.env").write_text(
            "AGENT_PODMAN_SSH_USER=worker\n"
            "AGENT_PODMAN_SSH_PORT=2223\n"
            "CONTAINER_HOST=ssh://worker@host.docker.internal:2223/run/user/501/podman.sock\n"
            "CONTAINER_SSHKEY=/run/secrets/agent-podman-key\n",
            encoding="utf-8",
        )
        (access / "id_ed25519").write_text("key", encoding="utf-8")
        (access / "known_hosts.sandbox").write_text("host", encoding="utf-8")
        result = self.run_launcher(
            AGENT_PODMAN_ACCESS_DIR=str(access), FAKE_RELAY_IP="10.0.0.8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        relay_runs = [
            call for call in calls
            if call[:2] == ["run", "--detach"]
            and any("codex-agent-podman-relay-" in item for item in call)
        ]
        self.assertEqual(1, len(relay_runs))
        self.assertIn("--cap-drop=ALL", relay_runs[0])
        self.assertIn("--read-only", relay_runs[0])
        self.assertEqual(
            "sha256:" + "0" * 64,
            relay_runs[0][relay_runs[0].index("/usr/bin/socat") + 1],
        )
        run = self.final_run()
        relay_name = relay_runs[0][relay_runs[0].index("--name") + 1]
        self.assertIn(f"CONTAINER_HOST=ssh://worker@{relay_name}:2222/run/user/501/podman.sock", run)
        self.assertIn(
            f"type=bind,src={access / 'id_ed25519'},dst=/run/secrets/agent-podman-key,readonly",
            run,
        )

    def test_rejects_incomplete_agent_podman_configuration(self) -> None:
        access = self.root / "agent-podman"
        access.mkdir()
        (access / "connection.env").write_text("CONTAINER_HOST=x\n", encoding="utf-8")
        result = self.run_launcher(AGENT_PODMAN_ACCESS_DIR=str(access))
        self.assertEqual(1, result.returncode)
        self.assertIn("Agent Podman access state is incomplete", result.stderr)
        self.assertEqual([], read_calls(self.docker_log))


if __name__ == "__main__":
    unittest.main()
