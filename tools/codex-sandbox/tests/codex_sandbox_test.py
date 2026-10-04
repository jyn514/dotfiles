from __future__ import annotations

import base64
import contextlib
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
    def test_detached_owner_worker_uses_log_and_null_stdin_before_bootstrap(self):
        launcher = runpy.run_path(str(LAUNCHER))
        run_agent = launcher["run_agent"]
        import host_pi_owner

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repo"
            git_directory = repository / ".git"
            git_directory.mkdir(parents=True)
            state = SimpleNamespace(
                repository=repository, git_repository=repository,
                container_repository=Path("/src/repo"), home=root / "home",
                host_working_directory=repository, skills_tmp=root / "skills",
                image="agent-image", codex_container="worker-container",
                codex_arguments=[], pi_model_session_id="test-session",
                host_editor=None, handoff_origin=None,
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
                    environment_file=lambda _environment: contextlib.nullcontext([]),
                    inspect_image=mock.Mock(return_value="inspected-image"),
                    workload=workload,
                )
                with mock.patch.object(host_pi_owner, "OWNER_LOG_FD", log.fileno()), \
                        mock.patch.object(host_pi_owner, "HostPiOwner") as owner, \
                        mock.patch.dict(run_agent.__globals__, {
                            "HOST_PI_BOOTSTRAP": object(), "OUTER_RUNTIME": runtime,
                            "scratch_directory": lambda: root,
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
                    owner.return_value.start.assert_not_called()
                log.seek(0)
                self.assertEqual({"[false, false, false]", "worker stderr"},
                                 set(log.read().splitlines()))

    def test_codex_pair_uses_mapped_virtiofs_identity_only_on_linux(self):
        identity = runpy.run_path(str(LAUNCHER))["codex_pair_identity"]
        state = SimpleNamespace(uid=1000, gid=1000)
        with mock.patch.dict(identity.__globals__, OUTER_RUNTIME=SimpleNamespace(
                provider="lima-docker", record={"virtiofs_map": {"uid": 1000}})):
            self.assertEqual((1000, 1000), identity(state))
        with mock.patch.dict(identity.__globals__, OUTER_RUNTIME=SimpleNamespace(
                provider="lima-docker", record={})):
            self.assertEqual((0, 0), identity(state))

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
            self.assertTrue((state.pi_agent_tmp / "extensions/codex-sidecar").is_dir())

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
                    actual = key(501, 20, "linux/arm64", base)
                self.assertNotEqual(actual, previous)
                previous = actual
            with mock.patch.dict(key.__globals__, ROOT=root, agent_sources=lambda: [source]):
                self.assertNotEqual(actual, key(502, 20, "linux/arm64", base))
                self.assertNotEqual(actual, key(501, 20, "linux/amd64", base))
                changed = SimpleNamespace(**{**vars(base), "config": "sha256:" + "d" * 64})
                self.assertNotEqual(actual, key(501, 20, "linux/arm64", changed))

    def test_failed_publication_keeps_coordination_until_cleanup(self):
        attach = runpy.run_path(str(LAUNCHER))['attach_proxies']
        lock = mock.Mock(shared=False)
        state = SimpleNamespace(proxy_lock=lock, repository=Path('/repo'),
            container_repository=Path('/src/repo'), proxy_prefix='proxy', proxy_state=Path('/state'),
            sidecar_image='image', image='agent', uid=501, gid=20,
            policy_source_present=True, manifest=Path('/manifest'), zuliprc=None,
            prepared_images=None)
        with mock.patch.dict(attach.__globals__, helper=mock.Mock(),
                _secure_codex_auth_directory=mock.Mock(return_value=None),
                attach_codex_sidecar=mock.Mock(return_value=[]),
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
            state = SimpleNamespace(proxy_lock=SimpleNamespace(shared=False), repository=root,
                                    container_repository=Path('/src/repo'),
                                    proxy_state=root / 'state', manifest=root / 'manifest')
            def helper(operation, *arguments):
                output.write_text('--read-only\n')
            for status, operation in (('shared', 'agent-args'), ('new', 'finalize')):
                with self.subTest(status=status):
                    state.proxy_lock.shared = status == 'shared'
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
        config = json.loads((ROOT / "config/agents/pi/pi-codex-subagents.json").read_text())
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
            self.assertEqual(str(ROOT / "config/agents/pi/pi-extensions/index.ts"), args[1])
            self.assertEqual("--extension", args[2])
            self.assertEqual(str(ROOT / "config/agents/pi/pi-extensions/guest-tools.ts"), args[3])
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
            resource_paths = launcher["host_pi_resource_paths"](SimpleNamespace(
                home=home,
                host_pi_package=host_pi_package,
                repository=host_repository,
                container_repository=Path("/src/personal/lapwing/stint"),
            ))
            result = subprocess.run(
                [str(TOOL / "sandbox-host-pi"), "--mode", "rpc"],
                env={**os.environ, "HOME": str(home),
                     "CODEX_SANDBOX_PI_RESOURCE_PATHS": json.dumps(resource_paths),
                     "FIXTURE_CORE": str(ROOT / "config/agents/pi/pi-extensions/guest-tools-core.ts"),
                     "FIXTURE_HOME": str(home),
                     "FIXTURE_HOST": str(host_repository),
                     "FIXTURE_PI_PACKAGE": str(host_pi_package)},
                capture_output=True, text=True, check=True,
            )
            output = json.loads(result.stdout)
            self.assertLess(
                output["args"].index(str(ROOT / "config/agents/pi/pi-extensions/index.ts")),
                output["args"].index(str(ROOT / "config/agents/pi/pi-extensions/guest-tools.ts")),
            )
            self.assertEqual(
                [
                    "Project config: /src/personal/lapwing/stint/config/agents/breq.md",
                    "Shared skill: /home/codex/.agents/skills/spec-review/SKILL.md",
                    "Agent instructions: <project_instructions path=\"/home/codex/.pi/agent/AGENTS.md\">",
                    "Pi examples: /opt/agent-pi/src/packages/coding-agent/examples",
                    "Guest package: /opt/agent-pi/src/packages/coding-agent/README.md",
                    "Guest checkout: /src/dotfiles/AGENTS.md",
                    f"Sibling location: {host_repository}-old/.agents/skills/spec-review/SKILL.md",
                ],
                output["prompt"].splitlines(),
            )


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

    def test_validation_does_not_initialize_a_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [str(LAUNCHER), "validate-cd", directory], capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((Path(directory) / ".jj").exists())

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
    def test_selects_guest_worker(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            state = SimpleNamespace(repository=Path(directory), agent_podman={}, uid=501, gid=20,
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
        self.assertEqual(["node", "/opt/agent-tools/bin/tool-worker.mjs"], calls[0][-2:])

    def test_fresh_session_reports_image_and_proxy_preparation(self) -> None:
        execute = runpy.run_path(str(LAUNCHER))["execute"]
        state = SimpleNamespace(repository=Path("/unused"))

        def acquire(value):
            value.proxy_lock = SimpleNamespace(shared=False)

        with mock.patch.dict(execute.__globals__, validate_repository=mock.Mock(),
                             recover_relays=mock.Mock(), acquire_lock=acquire,
                             load_repository_policy=mock.Mock(),
                             stage_skills=mock.Mock(side_effect=RuntimeError("stop after notice"))), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, "stop after notice"):
                execute(state)
        self.assertIn(
            "Preparing sandbox image and proxies from current repository policy; "
            "a cold build may take several minutes.",
            output.getvalue(),
        )

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
        with mock.patch.dict(execute.__globals__, validate_repository=mock.Mock(),
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
            state = SimpleNamespace(repository=repository, agent_podman=None, uid=501, gid=20,
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
                repository=Path(directory), agent_podman=None, uid=501, gid=20, codex_arguments=[],
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
            state = SimpleNamespace(repository=Path(directory), agent_podman={}, uid=501, gid=20, codex_arguments=[],
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
                setattr(value, "gateway_handle", object()) or [])
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

    def test_image_installs_host_editor_client(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "COPY --chmod=755 ./tools/codex-sandbox/image/host-editor "
            "/opt/agent-tools/bin/host-editor",
            dockerfile,
        )
        self.assertIn(
            "COPY ./tools/codex-sandbox/image/host-editor-protocol.json "
            "/opt/agent-tools/bin/host-editor-protocol.json",
            dockerfile,
        )
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
            "./tools/agent-podman/woodpecker-cli "
            "/opt/agent-tools/bin/woodpecker-cli",
            dockerfile,
        )

    def test_wrapped_tools_are_not_installed_on_the_public_command_path(self) -> None:
        dockerfile = SANDBOX_DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn(
            "./libexec/agent-wrappers/jj-conflict",
            dockerfile,
        )
        self.assertIn(
            "cp -a /usr/local/bin/jj /opt/agent-tools/libexec/jj", dockerfile
        )
        self.assertIn(
            "for command in bb java jj rg",
            dockerfile,
        )
        self.assertIn("for command in docker podman", dockerfile)
        self.assertIn(
            "ENV PATH=/libexec/sandbox-wrappers:/libexec/agent-wrappers:",
            dockerfile,
        )
        self.assertIn(
            "COPY --chmod=755 --chown=${AGENT_UID}:${AGENT_GID} "
            "./libexec/sandbox-wrappers/docker",
            dockerfile,
        )
        self.assertIn("ENV BB_REAL=/opt/agent-tools/libexec/bb", dockerfile)
        self.assertIn("ENV BB_SOURCE_ROOT=/", dockerfile)
        self.assertIn(
            "ENV CONTAINER_CLI_REAL_DIR=/opt/agent-tools/libexec", dockerfile
        )
        self.assertIn(
            "ENV JAVA_REAL=/opt/agent-tools/libexec/java", dockerfile
        )
        self.assertIn("ENV JJ_REAL=/opt/agent-tools/libexec/jj", dockerfile)
        self.assertIn("ENV RG_REAL=/opt/agent-tools/libexec/rg", dockerfile)

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
        super().setUp()
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

    def test_document_boundary_matches_on_both_sides_of_bridge(self) -> None:
        protocol = json.loads(
            (TOOL / "image" / "host-editor-protocol.json").read_text(encoding="utf-8")
        )
        self.assertEqual(protocol["max_document_bytes"], self.launcher["MAX_EDITOR_DOCUMENT_BYTES"])
        self.bridge._edit = lambda content: content
        self.start_bridge()

        accepted, content = self.run_client("a" * protocol["max_document_bytes"])
        rejected, _ = self.run_client("a" * (protocol["max_document_bytes"] + 1))

        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual(protocol["max_document_bytes"], len(content))
        self.assertEqual(1, rejected.returncode)
        self.assertIn("document is too large", rejected.stderr)

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
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
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
            if [ "$1 $2" = "info --format" ]; then
                printf '%s\n' linux/arm64
                exit
            fi
            if [ "$1 $2" = "image exists" ]; then
                [ "${FAKE_IMAGE_EXISTS:-1}" = 1 ] || [ -f "$FAKE_DOCKER_LOG.$3" ]
                exit
            fi
            if [ "$1 $2" = "image inspect" ]; then
                for image do :; done
                if [ "${FAKE_IMAGE_EXISTS:-1}" != 1 ] && [ "${image#codex-sandbox:}" != "$image" ] && [ ! -f "$FAKE_DOCKER_LOG.$image" ]; then
                    exit 1
                fi
                case " $* " in
                    *" --format "*) printf 'sha256:%064d\n' 0; exit 0 ;;
                esac
                case "$image" in
                    caddy@sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba)
                        printf '%s\n' '[{"Id":"sha256:6b08c1b9858ca9a7d99c1da13c3695081e0e604c6cf214ca26a7ce0e2c4fd9b4","RepoDigests":["caddy@sha256:1172d4213087d3fc30bafc7ff2c2896180eb0c41ff7f75f315568fb36cabdcba"],"RootFS":{"Layers":["sha256:0000000000000000000000000000000000000000000000000000000000000001"]},"Os":"linux","Architecture":"arm64"}]'
                        ;;
                    *) printf '[{"Id":"sha256:%064d","RootFS":{"Layers":["sha256:%064d"]},"Os":"linux","Architecture":"arm64"}]\n' 0 1 ;;
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
                previous=
                for argument do
                    [ "$previous" = --name ] && container=$argument
                    [ "$argument" = /opt/agent-tools/bin/tool-worker.mjs ] && worker=1
                    previous=$argument
                done
                if [ "$worker" = 1 ]; then
                    : > "$FAKE_DOCKER_LOG.worker.$container"
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
                    if [ -n "$FAKE_AGENT_READY" ]; then : > "$FAKE_AGENT_READY"; fi
                    while [ -f "$marker" ]; do sleep 1; done
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
                if [ "${FAKE_EDITOR_UNREACHABLE:-0}" = 1 ]; then
                    for argument do
                        case "$argument" in /trusted/bin/sandbox-gateway) exit 79 ;; esac
                    done
                fi
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
                publish|monitor) ;;
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
        creates = [call for call in read_calls(self.docker_log)
                   if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]
        self.assertEqual(1, len(creates))
        return creates[0]

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

    def test_host_pi_marks_guest_as_tool_worker(self) -> None:
        result = self.run_launcher(FAKE_WORKER_EXIT="17")
        self.assertNotEqual(0, result.returncode)  # The fake worker exits before Pi starts.
        creates = [call for call in read_calls(self.docker_log)
                   if call[:1] == ["create"] and "/opt/agent-tools/bin/tool-worker.mjs" in call]
        self.assertEqual(1, len(creates), result.stderr)
        self.assertIn("CODEX_SANDBOX_TOOL_WORKER=1", creates[0])

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
        renamed = self.root / "renamed-agents-source.md"
        renamed.write_text("renamed source\n", encoding="utf-8")
        sources = launcher["installed_config_sources"]()
        state = SimpleNamespace(home=self.home, repository=self.repo, skills_tmp=None)
        try:
            with mock.patch.dict(
                sources, {"$HOME/.pi/agent/AGENTS.md": renamed}, clear=False,
            ):
                launcher["stage_skills"](state)
            self.assertEqual(
                "renamed source\n",
                (state.skills_tmp / "config/agents").read_text(encoding="utf-8"),
            )
        finally:
            if state.skills_tmp is not None:
                shutil.rmtree(state.skills_tmp)

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
            agents = (state.skills_tmp / "config/agents").read_text(encoding="utf-8")
            self.assertEqual(
                "@breq.md\n"
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
                (state.skills_tmp / "config/settings").read_text(encoding="utf-8")
            )
            self.assertEqual(
                "/opt/agent-tools/bin/host-editor", settings["externalEditor"]
            )
            source = json.loads(launcher["installed_config_source"](
                "$HOME/.pi/agent/settings.json"
            ).read_text(encoding="utf-8"))
            self.assertNotIn("externalEditor", source)
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
            # Pane-local lookup is empty when remain-on-exit is inherited.
            if arguments[:2] == ["tmux", "show-options"] and "-A" not in arguments:
                return SimpleNamespace(stdout="")
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
        path = os.pathsep.join((str(ROOT / "bin"), str(self.fake_bin), os.environ["PATH"]))
        result = self.run_launcher("auth", "login", PATH=path)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"{self.home / '.codex-sandbox-auth'}\t{self.home / '.codex/developer-instructions.md'}\tlogin\n",
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
        self.assertIn(
            f"type=bind,src={ROOT / 'config/agents/codex/codex.toml'},"
            "dst=/home/codex/.codex/dotfiles.config.toml,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'config/agents/codex/codex-developer-instructions.md'},"
            "dst=/home/codex/.codex/developer-instructions.md,readonly",
            run,
        )
        self.assertIn(
            f"type=bind,src={ROOT / 'config/agents/breq.md'},"
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
        staged_mounts = [
            item for item in run
            if any(item.endswith(f"dst={destination},readonly") for destination in (
                "/home/codex/.agents/shared.md",
                "/home/codex/.agents/coordination-dialect.md",
                "/home/codex/.pi/agent/AGENTS.md",
                "/home/codex/.pi/agent/breq.md",
                "/home/codex/.pi/agent/settings.json",
                "/home/codex/.pi/agent/mcp.json",
                "/home/codex/.pi/agent/keybindings.json",
            ))
        ]
        self.assertEqual(7, len(staged_mounts))
        staged_sources = [
            Path(item.split(",src=", 1)[1].split(",dst=", 1)[0])
            for item in staged_mounts
        ]
        self.assertEqual(1, len({source.parent for source in staged_sources}))
        self.assertTrue(all(not source.is_relative_to(ROOT) for source in staged_sources))
        self.assertIn(
            f"type=bind,src={ROOT / 'config/agents/pi/pi-extensions'},"
            "dst=/home/codex/.pi/agent/pi-extensions,readonly",
            run,
        )
        self.assertNotIn("pi-agent-", " ".join(run))
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", run)
        self.assertIn("CODEX_SANDBOX_TOOL_WORKER=1", run)
        self.assertIn("SANDBOX_PROXY_DIR=/run/sandbox-proxies", run)
        self.assertNotIn("EDITOR=/opt/agent-tools/bin/host-editor", run)
        self.assertNotIn("VISUAL=/opt/agent-tools/bin/host-editor", run)
        self.assertTrue(any(item.startswith("CODEX_SANDBOX_EDITOR_ADDRESS=") for item in run))
        self.assertIn("CODEX_SANDBOX_EDITOR_TOKEN", run)
        self.assertFalse(any(item.startswith("CODEX_SANDBOX_EDITOR_TOKEN=") for item in run))
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

    def test_cancelled_codex_broker_persists_then_recovers_without_creation(self) -> None:
        launcher = runpy.run_path(str(LAUNCHER))
        auth = self.home / ".codex-sandbox-auth"
        auth.mkdir(mode=0o700)
        (auth / "auth.json").write_text('{"tokens":{}}\n', encoding="utf-8")
        (auth / "auth.json").chmod(0o600)
        proxy_state = self.root / "broker-state.json"
        proxy_state.write_text('{"proxies":[]}', encoding="utf-8")
        state = SimpleNamespace(
            codex_sidecar_container="cancelled-auth", sidecar_image="sha256:" + "0" * 64,
            uid=os.getuid(), gid=os.getgid(), proxy_state=proxy_state,
        )
        cancelled = threading.Event()
        cancelled.set()
        calls = []

        def fake_run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:3] == ["docker", "container", "ls"]:
                return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(arguments, 1, stdout="", stderr="unexpected command")

        with mock.patch.dict(launcher["start_codex_sidecar"].__globals__, run=fake_run), \
                mock.patch.dict(launcher["start_codex_sidecar"].__globals__,
                                resolve_caddy_image=mock.Mock()) as patched:
            with self.assertRaisesRegex(launcher["LauncherError"], "cancelled"):
                launcher["start_codex_sidecar"](state, auth.resolve(), cancelled=cancelled)
            patched["resolve_caddy_image"].assert_not_called()
        self.assertFalse(any(call[:2] == ["docker", "run"] for call in calls))
        self.assertNotIn("auth", json.loads(proxy_state.read_text(encoding="utf-8")))

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
        self.assertEqual(2, len(sidecars))
        helper = next(call for call in sidecars if "/trusted/bin/profile-helper" in call)
        caddy = next(call for call in sidecars if "/trusted/bin/profile-helper" not in call)
        credential_mount = f"type=bind,src={auth.resolve()},dst=/var/lib/codex-auth"
        self.assertIn(credential_mount, helper)
        self.assertNotIn(credential_mount, caddy)
        self.assertIn("--read-only", helper)
        self.assertIn("--read-only", caddy)
        self.assertEqual("0:0", helper[helper.index("--user") + 1])
        self.assertEqual("0:0", caddy[caddy.index("--user") + 1])
        socket_mounts = [item for call in (helper, caddy) for item in call
                         if item.startswith("type=volume,") and "dst=/run/profile-helper" in item]
        self.assertEqual(2, len(socket_mounts))
        self.assertEqual(socket_mounts[0], socket_mounts[1].removesuffix(",readonly"))
        self.assertIn("--entrypoint", helper)
        self.assertEqual("sha256:" + "0" * 64, helper[helper.index("--entrypoint") + 2])
        self.assertTrue(any(item.startswith("caddy@sha256:") for item in caddy))
        self.assertEqual("run", caddy[-3])
        self.assertEqual("/etc/caddy/caddy.json", caddy[-1])
        labels = [helper[index + 1] for index, value in enumerate(helper) if value == "--label"]
        self.assertIn("dev.codex.credential-domain=codex", labels)
        self.assertTrue(any(value.startswith("dev.codex.service-owner=") for value in labels))
        caddy_name = caddy[caddy.index("--name") + 1]
        readiness = [call for call in calls if call[:2] == ["exec", caddy_name]
                     and call[-1] == "http://127.0.0.1:8787/ready"]
        self.assertEqual(1, len(readiness))
        agent = self.final_run()
        self.assertFalse(any(str(auth) in item for item in agent))
        self.assertTrue(any(item.startswith("CODEX_SIDECAR_URL=http://codex-auth-proxy-") for item in agent))
        self.assertIn(
            f"type=bind,src={ROOT / 'tools/codex-sandbox/auth-proxy/pi-extension'},"
            "dst=/home/codex/.pi/agent/extensions/codex-sidecar,readonly",
            agent,
        )

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
        git_mount = f"type=bind,src={git_dir.resolve()},dst=/src/repository/.git,readonly"
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
        self.assertIn("codex-gateway-", docker_log)
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
        self.assertTrue(any(any(argument.endswith("tools/codex-sandbox/image/Dockerfile")
                                for argument in call) for call in builds))
        self.assertIn("sha256:" + "0" * 64, self.final_run())

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
        self.assertIn("codex-gateway-", docker_log)
        actions = [call[1] for call in read_calls(self.python_log) if len(call) > 1]
        self.assertIn("attach", actions)
        self.assertNotIn("hold-lock", actions)

    def test_cli_literal_print_and_rpc_prompt_after_separator_still_holds_interactive_lease(self) -> None:
        ready = self.root / "literal-prompt-ready"
        result = self.run_launcher("--", "-p", "--mode", "rpc", FAKE_HOST_PI_READY=str(ready))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(ready.exists())
        self.assertIsInstance(json.loads(ready.read_text())["owner"], str)

    @unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
    def test_cli_side_keeps_exact_worker_and_relays_after_original_sigkill(self) -> None:
        server = "sandbox-cli-owner-" + uuid.uuid4().hex
        started = subprocess.run(["tmux", "-L", server, "new-session", "-d", "-P", "-F",
                                  "#{pane_id}", "sleep 60"], text=True, capture_output=True)
        if started.returncode:
            self.skipTest(started.stderr)
        pane = started.stdout.strip()
        tmux = subprocess.check_output(["tmux", "-L", server, "display-message", "-p",
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
            subprocess.run(["tmux", "-L", server, "kill-pane", "-t", pane], check=True)
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
            self.assertEqual(1, len(gateway_starts))
            # The existing engine fixture reports relay presence as absent. Its
            # cleanup presence query (rather than an unsafe name-based removal)
            # must still occur only after the final lease.
            self.assertTrue(any(call[:2] == ["container", "ls"] for call in read_calls(self.docker_log)))
        finally:
            subprocess.run(["tmux", "-L", server, "kill-server"], capture_output=True)
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_host_editor_relay_is_isolated_and_injected(self) -> None:
        result = self.run_launcher()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = read_calls(self.docker_log)
        relay = next(
            call for call in calls
            if call[:2] == ["run", "--detach"]
            and any("codex-gateway-" in item for item in call)
        )
        self.assertIn("--cap-drop=ALL", relay)
        self.assertIn("--security-opt=no-new-privileges", relay)
        self.assertIn("--read-only", relay)
        self.assertIn("--pids-limit", relay)
        self.assertIn("--memory", relay)
        self.assertIn("--cpus", relay)
        self.assertIn("--http-proxy=false", relay)
        self.assertIn("/trusted/bin/sandbox-gateway", relay)
        self.assertNotIn('--podman-port', relay)
        editor_networks = [
            call for call in calls if call[:2] == ["network", "create"]
            and any("codex-gateway-" in item for item in call)
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
        self.assertIn('gateway startup failed', result.stderr)
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
            and any("codex-gateway-" in item for item in call)
        ]
        self.assertEqual(1, len(relay_runs))
        networks = [call for call in calls if call[:2] == ['network', 'create']
                    and any('codex-gateway-' in item for item in call)]
        self.assertEqual(len(networks), 2, 'editor and Podman must share one private network pair')
        self.assertNotIn('--cpus', relay_runs[0], 'editor limits must not throttle Podman')
        self.assertIn('--editor-port', relay_runs[0])
        self.assertIn('--podman-port', relay_runs[0])
        self.assertFalse(any('agent-podman-key' in item or 'EDITOR_TOKEN' in item for item in relay_runs[0]))
        self.assertIn("--cap-drop=ALL", relay_runs[0])
        self.assertIn("--read-only", relay_runs[0])
        self.assertEqual(
            "sha256:" + "0" * 64,
            relay_runs[0][relay_runs[0].index("/trusted/bin/sandbox-gateway") + 1],
        )
        run = self.final_run()
        relay_name = relay_runs[0][relay_runs[0].index("--name") + 1]
        self.assertIn(f"CONTAINER_HOST=ssh://worker@{relay_name}:2222/run/user/501/podman.sock", run)
        self.assertIn(f'CODEX_SANDBOX_EDITOR_ADDRESS={relay_name}:2223', run)
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
