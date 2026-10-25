"""Launcher composition with provider fakes, not Linux/macOS VM acceptance.

The host child and lifetime pipe are real. Provider container/network effects and
its guest readiness result are fake; native provider acceptance remains separate.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
from sandbox_runtime import ContainerRuntime, VMRuntime
NATIVE_REVISION = (TOOL.parent / 'tic-proxy/native-revision').read_text().strip()
from trusted_services import LifecycleError, LifecycleState, ResourcePresence


class LocalPythonRelay:
    """Run the staged wrapper natively; replace only its provider container."""

    def __init__(self, script, target):
        from tic_relay import PORT
        self.port = PORT
        # The production CLI has a fixed private-container port. This opt-in
        # local substitute requires that port to be free and never adopts an
        # existing listener or changes the wrapper's public CLI for the test.
        with socket.socket() as reservation:
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reservation.bind(('127.0.0.1', PORT))
        self.script = script
        self.environment = {'PYTHONDONTWRITEBYTECODE': '1'}
        self.process = subprocess.Popen(
            [sys.executable, str(script), '--target-host', '127.0.0.1', '--target-port', str(target)],
            env=self.environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            result = self.probe()
            if result.returncode or self.process.poll() is not None:
                raise RuntimeError('owned Python relay failed local listener readiness')
        except BaseException:
            self.stop()
            raise

    def probe(self):
        return subprocess.run([sys.executable, str(self.script), '--probe'],
                              env=self.environment, capture_output=True, text=True, timeout=7)

    def stop(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
        self.process.stderr.close()


class FakeProvider:
    provider = 'podman'
    host_address = 'host.docker.internal'

    def __init__(self, root, platform):
        self.platform = platform
        self.events = []
        self.present = set()
        self.host = SimpleNamespace(
            state=root, check_binds=mock.Mock(side_effect=lambda sources:
                                            self.events.append(('binds', sources))))
        (root / 'scratch').mkdir(parents=True, exist_ok=True)
        self.probe_status = 0
        self.listener_status = 0

    def build_platform(self):
        return self.platform

    def verify_builder_image(self, image):
        self.events.append(('image', image))
        return image

    def network_address(self, container, network):
        return '10.23.0.2' if '-link-' in network else '10.24.0.2'

    def network_addresses(self, container, networks):
        return {network: self.network_address(container, network) for network in networks}

    @contextmanager
    def environment_file(self, values):
        self.events.append(('environment', dict(values)))
        yield ['--env-file', '/private/disposable-env']

    def run(self, argv, **kwargs):
        self.events.append(('probe', argv))
        return SimpleNamespace(returncode=self.listener_status if argv[-1] == '--probe' else self.probe_status)


class FakeMacProvider(FakeProvider, VMRuntime):
    provider = 'lima-docker'
    host_address = 'host.lima.internal'


class TicLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.launcher = runpy.run_path(str(TOOL / 'codex-sandbox'))
        self.globals = self.launcher['start_tic'].__globals__
        self.home = self.root / 'home'
        self.home.mkdir()
        self.install = self.root / 'owned-process-fixture'
        self.install.mkdir(parents=True)
        workspace = self.root / 'workspace'
        common = workspace / '.git'
        common.mkdir(parents=True)
        self.state = SimpleNamespace(
            home=self.home, codex_auth_directory=self.home / '.codex',
            repository=workspace, host_working_directory=workspace / 'nested',
            workspaces=[SimpleNamespace(host_root=workspace, common_dir=common)],
            capabilities={'tic'}, sidecar_image='sha256:helper', image='sha256:agent',
            suffix='first', tic_handle=None, tic_resources=None, tic_environment={})
        self.native = self.install / 'native-ti'
        self.native.write_text('#!/bin/sh\nexit 99\n')
        self.native.chmod(0o700)
        Path(str(self.native) + '.tic-proxy.json').write_text('{}')
        self.broker = self.install / 'tic-broker'
        self.broker.write_text(
            f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(TOOL / "tests")!r})\n'
            'from tic_broker_fixture import main\nmain("ready")\n')
        self.broker.chmod(0o700)
        self.client = self.install / 'guest-ti'
        self.manifest = self.install / 'process-fixture.json'
        self.real_resolver = self.globals['resolved_tic_build']
        self.globals['resolved_tic_build'] = self.fixture_build
        self.write_build('linux/amd64')
        self.context = {'user_name': 'Accepted Author', 'user_email': 'accepted@example.invalid',
                        'namespace': 'fixture'}
        self.addCleanup(self.stop)

    def stop(self):
        if self.state.tic_handle is not None:
            self.state.tic_handle.stop()

    def write_build(self, platform, header=None):
        if header is None:
            header = bytearray(64)
            header[:6] = b'\x7fELF\x02\x01'
            header[18:20] = (62 if platform == 'linux/amd64' else 183).to_bytes(2, 'little')
        self.client.write_bytes(header)
        self.client.chmod(0o700)
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        value = dict(version=1, native_revision=NATIVE_REVISION, policy_version=1,
                     broker_executable=str(self.broker), broker_sha256=digest(self.broker),
                     native_executable=str(self.native), native_sha256=digest(self.native),
                     guest_client_executable=str(self.client), guest_client_sha256=digest(self.client),
                     guest_client_platform=platform)
        self.manifest.write_text(json.dumps(value))

    def fixture_build(self, state=None):
        from tic_broker import InstalledTicBuild
        value = json.loads(self.manifest.read_text())
        build = InstalledTicBuild(Path(value['broker_executable']), value['broker_sha256'],
                                  Path(value['native_executable']), value['native_sha256'],
                                  Path(value['guest_client_executable']), value['guest_client_sha256'],
                                  value['guest_client_platform'], value['native_revision'])
        build.verify()
        return build

    @contextmanager
    def provider(self, mac=False, context=True):
        runtime = (FakeMacProvider if mac else FakeProvider)(self.root / ('mac' if mac else 'linux'),
                                                            'linux/arm64' if mac else 'linux/amd64')
        def create(state, name, *, internal, owner):
            runtime.events.append(('network', name, internal))
            runtime.present.add(name)
        def run(argv, **kwargs):
            runtime.events.append(('container', argv))
            runtime.present.add(argv[argv.index('--name') + 1])
            return SimpleNamespace(returncode=0)
        def remove(runtime_arg, kind, name, owner, **kwargs):
            self.assertIs(runtime_arg, runtime)
            runtime.events.append(('remove', name))
            runtime.present.discard(name)
        patches = {'OUTER_RUNTIME': runtime, 'create_relay_network': create, 'run': run,
                   'proxy_flags': lambda: [], 'remove_owned_resource': remove,
                   '_gateway_network_presence': lambda name, owner: (
                       ResourcePresence.OWNED if name in runtime.present else ResourcePresence.ABSENT),
                   '_gateway_container_presence': lambda name, owner: (
                       ResourcePresence.OWNED if name in runtime.present else ResourcePresence.ABSENT)}
        if context:
            patches['inspect_tic_context'] = mock.Mock(return_value=self.context)
        original_bridge = self.globals['TicBrokerLaunch'].start_bridge
        def start_bridge(handle, peers):
            runtime.host_bridge = original_bridge(handle, peers)
            return runtime.host_bridge
        with mock.patch.dict(self.globals, patches), mock.patch.object(
                self.globals['TicBrokerLaunch'], 'start_bridge', start_bridge):
            try:
                yield runtime
            finally:
                self.stop()

    def exchange(self, handle, address=None):
        host, port = (address or handle.address).rsplit(':', 1)
        with socket.create_connection((host, int(port)), timeout=2) as connection:
            data = json.dumps({'token': handle.token, 'request': {
                'version': 2, 'command': 'tic', 'argv': ['--help'], 'stdin': ''}}).encode()
            connection.sendall(struct.pack('!I', len(data)) + data)
            connection.shutdown(socket.SHUT_WR)
            response = bytearray()
            while chunk := connection.recv(65536):
                response.extend(chunk)
        return json.loads(response[4:])

    def assert_tic_unavailable(self, message):
        with mock.patch('sys.stderr', new_callable=io.StringIO) as warning:
            self.assertEqual([], self.launcher['start_tic'](self.state))
        self.assertIn('warning: TicGit unavailable for this session', warning.getvalue())
        self.assertIn(message, warning.getvalue())
        self.assertEqual({}, self.state.tic_environment)

    def test_explicit_opt_out_does_not_resolve_artifacts_or_start_resources(self):
        self.state.capabilities = set()
        self.manifest.unlink()
        self.assertEqual([], self.launcher['start_tic'](self.state))
        self.assertIsNone(self.state.tic_handle)
        self.assertFalse((self.home / '.cache').exists())

    def test_new_policy_defaults_and_explicit_true_warn_while_false_has_no_host_contact(self):
        module = self.globals['proxy_module']()
        for source in (None, {'version': 1, 'commands': {}}, {'version': 2},
                       {'version': 1, 'commands': {}, 'capabilities': {'tic': True}},
                       {'version': 2, 'capabilities': {'tic': True}},
                       {'version': 1, 'commands': {}, 'capabilities': {'tic': False}},
                       {'version': 2, 'capabilities': {'tic': False}}):
            with self.subTest(source=source):
                policy = None
                if source is not None:
                    policy = self.root / 'source-policy.json'
                    policy.write_text(json.dumps(source))
                manifest = module.load_manifest_file(policy)
                self.state.capabilities = {name for name, selected in manifest['capabilities'].items() if selected}
                self.state.tic_environment = {'SANDBOX_TIC_ENDPOINT': 'stale', 'SANDBOX_TIC_TOKEN': 'stale'}
                resolve = mock.Mock(side_effect=self.launcher['LauncherError']('owned bundle build failed'))
                with self.provider() as runtime, mock.patch.dict(self.globals, resolved_tic_build=resolve):
                    if 'tic' in self.state.capabilities:
                        self.assert_tic_unavailable('owned bundle build failed')
                        resolve.assert_called_once_with(self.state)
                    else:
                        self.assertEqual([], self.launcher['start_tic'](self.state))
                        resolve.assert_not_called()
                        self.assertFalse(runtime.events)
                    self.assertEqual({}, self.state.tic_environment)
                    self.assertIsNone(self.state.tic_handle)
                    self.assertFalse(runtime.present)

    def test_missing_first_use_source_warns_without_accepting_bundle_or_starting_resources(self):
        with self.provider() as runtime, mock.patch.dict(self.globals, resolved_tic_build=self.real_resolver):
            self.assert_tic_unavailable('requires a trusted native repository path')
            self.assertIsNone(self.state.tic_handle)
            self.assertFalse(runtime.present)
        self.assertEqual(['.resolve.lock'], [path.name for path in
                         (self.home / '.cache/codex-sandbox/tic').iterdir()])

    def test_startup_warning_does_not_swallow_process_control_or_workspace_authority_rejection(self):
        for failure in (KeyboardInterrupt(), SystemExit(9)):
            with self.subTest(failure=failure), self.provider(), mock.patch.dict(
                    self.globals, _start_tic=mock.Mock(side_effect=failure)):
                with self.assertRaises(type(failure)), mock.patch('sys.stderr', new_callable=io.StringIO) as warning:
                    self.launcher['start_tic'](self.state)
                self.assertEqual('', warning.getvalue())
        self.state.workspaces[0].host_root = self.root / 'another-workspace'
        resolve = mock.Mock(side_effect=AssertionError('invalid authority reached artifact resolution'))
        with self.provider(), mock.patch.dict(self.globals, resolved_tic_build=resolve):
            with self.assertRaisesRegex(self.launcher['LauncherError'], 'workspace authority'):
                self.launcher['start_tic'](self.state)
        resolve.assert_not_called()

    def test_startup_interrupt_is_not_replaced_by_a_cleanup_exception(self):
        broker = self.globals['TicBrokerLaunch']
        stop = broker.stop
        def cleanup_then_fail(handle, *args):
            stop(handle, *args)
            raise RuntimeError('owned cleanup reporting failed')
        for failure in (KeyboardInterrupt(), SystemExit(9)):
            with self.subTest(failure=failure), self.provider():
                with mock.patch.object(broker, 'stop', autospec=True, side_effect=cleanup_then_fail), mock.patch.dict(
                        self.globals, stage_tic_client=mock.Mock(side_effect=failure)):
                    with self.assertRaises(type(failure)), mock.patch('sys.stderr', new_callable=io.StringIO) as warning:
                        self.launcher['start_tic'](self.state)
                    self.assertIn('startup cleanup failed', warning.getvalue())
                    self.assertNotIn('continuing without it', warning.getvalue())
                    self.assertIsNone(self.state.tic_handle.process)
                    self.assertEqual({}, self.state.tic_environment)

    def test_failed_startup_retains_cleanup_ownership_but_stops_broker_when_provider_cleanup_fails(self):
        with self.provider() as runtime:
            runtime.probe_status = 125
            remove = mock.Mock(side_effect=RuntimeError('owned provider removal failed'))
            with mock.patch.dict(self.globals, remove_owned_resource=remove):
                self.assert_tic_unavailable('readiness failed')
                handle = self.state.tic_handle
                self.assertIsNone(handle.process)
                self.assertEqual('', handle.token)
                self.assertIsNone(handle.address)
                self.assertEqual(LifecycleState.CLEANUP_FAILED, handle.lifecycle.state)
                self.assertIsNotNone(self.state.tic_resources)
                self.assertTrue(runtime.present)
                self.assertEqual(handle.owner, handle.registry.owner)
            result = handle.stop()
            self.assertFalse(result.remaining)
            self.assertFalse(runtime.present)

    def test_tic_only_transport_build_failure_does_not_block_new_session(self):
        self.state.deferred_signal = None
        self.state.proxy_lock = SimpleNamespace(shared=False)
        self.state.sidecar_image = ''
        self.state.manifest = self.root / 'snapshot.json'
        self.state.manifest.write_text(json.dumps({'commands': {}}))
        empty = ('validate_repository', 'acquire_lock', 'load_repository_policy', 'bind_repository_policy',
                 'recover_relays', 'stage_skills', 'agent_repository_mounts', 'prepare_host_pi_resources',
                 'register_tmux_pane', 'ensure_network', 'prepare_gateway', 'attach_proxies')
        replacements = {name: mock.Mock(return_value=[]) for name in empty}
        prepare = mock.Mock(return_value=None)
        transport = mock.Mock(side_effect=self.launcher['LauncherError']('owned transport build failed'))
        agent = mock.Mock(return_value=19)
        replacements.update(prepare_declared_images=prepare, run_agent=agent,
                            resolve_model_image=mock.Mock(return_value=self.state.image),
                            resolve_sidecar_image=transport, _secure_codex_auth_directory=lambda state: None)
        with self.provider() as runtime, mock.patch.dict(self.globals, replacements), mock.patch(
                'sys.stderr', new_callable=io.StringIO) as warning:
            self.assertEqual(19, self.launcher['execute'](self.state))
            self.assertIn('owned transport build failed', warning.getvalue())
            prepare.assert_called_once_with(self.state, {'commands': {}}, False)
            transport.assert_called_once_with()
            agent.assert_called_once()
            self.assertNotIn('dst=/opt/agent-tools/bin/ti', ' '.join(agent.call_args.args[1]))
            self.assertEqual({}, self.state.tic_environment)
            self.assertIsNone(self.state.tic_handle)
            self.assertFalse(runtime.present)

    def test_first_use_source_option_configures_host_then_forwards_normal_pi_arguments(self):
        import tic_artifact
        repository = self.root / 'native-source'
        for options in (['--set-tic-native-source', str(repository)],
                        ['--set-tic-native-source=' + str(repository)]):
            with self.subTest(options=options), mock.patch.object(tic_artifact, 'configure_native_source') as configure, mock.patch(
                    'host_pi_owner.detached_frontend', return_value=17) as frontend, mock.patch('threading.active_count', return_value=1), mock.patch.dict(
                        self.globals, {'image_runtime': mock.Mock(side_effect=AssertionError('no provider'))}):
                with mock.patch('pathlib.Path.home', return_value=self.home):
                    self.assertEqual(17, self.launcher['main']([*options, '--session-id', 'fixture']))
                configure.assert_called_once_with(self.home, repository, replace=True)
                self.assertEqual(['--session-id', 'fixture'], frontend.call_args.args[0])

    def test_first_use_source_option_failure_never_launches_pi_or_changes_configuration(self):
        import tic_artifact
        for arguments in (['--set-tic-native-source'], ['--set-tic-native-source='],
                          ['--set-tic-native-source=a', '--set-tic-native-source=b']):
            with self.subTest(arguments=arguments), mock.patch.object(tic_artifact, 'configure_native_source') as configure, mock.patch(
                    'host_pi_owner.detached_frontend', side_effect=AssertionError('no Pi')):
                self.assertEqual(1, self.launcher['main'](arguments))
                configure.assert_not_called()
        with mock.patch.object(tic_artifact, 'configure_native_source', side_effect=ValueError('owned invalid source')), mock.patch(
                'host_pi_owner.detached_frontend', side_effect=AssertionError('no Pi')):
            self.assertEqual(1, self.launcher['main'](['--set-tic-native-source', '/fixture']))
        with mock.patch.object(tic_artifact, 'configure_native_source') as configure, mock.patch(
                'host_pi_owner.detached_frontend', return_value=0) as frontend, mock.patch('threading.active_count', return_value=1):
            arguments = ['--', '--set-tic-native-source', '/not-a-setting']
            self.assertEqual(0, self.launcher['main'](arguments))
            configure.assert_not_called()
            self.assertEqual(arguments, frontend.call_args.args[0])

    def test_normal_tic_on_resolver_cold_cache_invokes_owned_builder(self):
        from tic_artifact import ROOT as proxy_root
        import tic_artifact
        # Only source choice is injected. The ordinary launcher calls its real
        # resolver and stages the builder result; this is not a custom starter.
        source_repository = self.root / 'trusted-native-source'
        source_repository.mkdir()
        setting = self.home / '.config/codex-sandbox/tic-native-source'
        setting.parent.mkdir(parents=True)
        setting.write_text(str(source_repository) + '\n')
        setting.chmod(0o600)
        import bundle
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader('launcher_bundle_fixture', str(proxy_root / 'build-local'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        builder = importlib.util.module_from_spec(spec)
        loader.exec_module(builder)
        header = bytearray(120)
        header[:8] = b'\x7fELF\x02\x01\x01\x00'
        header[18:20] = (62).to_bytes(2, 'little')
        header[32:40] = (64).to_bytes(8, 'little')
        header[54:56] = (56).to_bytes(2, 'little')
        self.client.write_bytes(header)
        Path(str(self.native) + '.tic-proxy.json').write_text(json.dumps(dict(
            native_revision=NATIVE_REVISION, policy_version=1, sha256=bundle.sha256(self.native))))
        source = builder.stage_bundle(self.install, NATIVE_REVISION, self.native, self.broker,
                                      self.client, 'linux/amd64')
        with self.provider() as runtime, mock.patch.object(tic_artifact, 'build_bundle', return_value=source) as build:
            resolved = self.real_resolver(self.state)
            build.assert_called_once_with(source_repository,
                                           bundle.build_identity(bundle.host_platform(), 'linux/amd64'))
            self.assertTrue(resolved.native_executable.is_relative_to(self.home / '.cache/codex-sandbox/tic'))
            self.assertFalse(resolved.native_executable.is_relative_to(self.install))
            self.assertFalse(runtime.events)
            build.reset_mock()
            self.assertEqual(resolved, self.real_resolver(self.state))
            build.assert_not_called()
        for directory, _, _ in os.walk(self.home, followlinks=False):
            Path(directory).chmod(0o700)

    def test_real_resolver_excludes_writable_workspace_and_skills_aliases_before_provisioning(self):
        import tic_artifact
        alias = self.root / 'skills-alias'
        alias.symlink_to(self.home, target_is_directory=True)
        for source in ('workspace', 'skills'):
            with self.subTest(source=source), self.provider() as runtime, mock.patch.object(tic_artifact, 'build_bundle') as build:
                if source == 'workspace':
                    self.state.workspaces.append(SimpleNamespace(host_root=self.home))
                else:
                    self.state.workspaces.pop()
                    self.state.skills_source = alias
                with self.assertRaisesRegex(self.launcher['LauncherError'], 'guest-writable'):
                    self.real_resolver(self.state)
                build.assert_not_called()
                self.assertFalse(runtime.events)
        self.assertFalse((self.home / '.cache').exists())

    def test_normal_cold_cache_reports_unsettled_native_source_without_creating_cache(self):
        with self.provider(), self.assertRaisesRegex(self.launcher['LauncherError'], 'requires a trusted native repository path'):
            self.real_resolver(self.state)
        cache = self.home / '.cache/codex-sandbox/tic'
        self.assertEqual(['.resolve.lock'], [p.name for p in cache.iterdir()])

    def test_linux_and_mac_fake_provider_compose_required_host_child_and_staged_client(self):
        for mac in (False, True):
            with self.subTest(mac=mac):
                self.write_build('linux/arm64' if mac else 'linux/amd64')
                with self.provider(mac) as runtime:
                    args = self.launcher['start_tic'](self.state)
                    handle = self.state.tic_handle
                    self.assertEqual(LifecycleState.ATTACHED, handle.lifecycle.state)
                    self.assertEqual(str(self.state.repository), handle.config['workspace'])
                    self.assertEqual(str(self.state.workspaces[0].common_dir), handle.config['common_dir'])
                    self.assertNotEqual(str(self.state.host_working_directory), handle.config['workspace'])
                    self.assertEqual(self.context['user_name'], handle.config['user_name'])
                    self.assertEqual('fixture response', self.exchange(handle)['stdout'])
                    mount = args[args.index('--mount') + 1]
                    self.assertTrue(mount.endswith('dst=/opt/agent-tools/bin/ti,readonly'))
                    staged = Path(mount.split('src=')[1].split(',')[0])
                    self.assertEqual(self.client.read_bytes(), staged.read_bytes())
                    self.assertEqual(0o555, staged.stat().st_mode & 0o777)
                    self.assertEqual(0o700, staged.parent.stat().st_mode & 0o777)
                    relay_dir = staged.parent / 'relay'
                    self.assertEqual(0o555, relay_dir.stat().st_mode & 0o777)
                    self.assertEqual({'tic_relay.py', 'host_tcp_bridge.py'},
                                     {path.name for path in relay_dir.iterdir()})
                    for path in relay_dir.iterdir():
                        self.assertEqual(0o444, path.stat().st_mode & 0o777)
                        self.assertEqual((TOOL / path.name).read_bytes(), path.read_bytes())
                    if mac:
                        self.assertTrue(staged.is_relative_to(runtime.host.state / 'scratch'))
                        runtime.host.check_binds.assert_called_once_with(
                            [(str(staged), False), (str(relay_dir), False)])
                    self.assertEqual('10.23.0.2:2225', self.state.tic_environment['SANDBOX_TIC_ENDPOINT'])
                    probe_environment = next(item[1] for item in runtime.events if item[0] == 'environment')
                    self.assertEqual(handle.token, probe_environment['SANDBOX_TIC_TOKEN'])
                    self.assertEqual('127.0.0.1:2225', probe_environment['SANDBOX_TIC_ENDPOINT'])
                    container = next(item[1] for item in runtime.events if item[0] == 'container')
                    self.assertIn('/usr/local/bin/python3', container)
                    self.assertIn('/trusted/tic/tic_relay.py', container)
                    self.assertIn('PYTHONDONTWRITEBYTECODE=1', container)
                    self.assertIn(f'type=bind,src={relay_dir},dst=/trusted/tic,readonly', container)
                    self.assertIn(self.state.sidecar_image, container)
                    self.assertEqual(['--probe', '--help'],
                                     [event[1][-1] for event in runtime.events if event[0] == 'probe'])
                    self.assertNotIn(handle.token, ' '.join(container))
                    self.assertNotIn(handle.token, ' '.join(args))
                    handle.stop()
                    self.assertFalse(runtime.present)
                    self.assertFalse(staged.exists())

    def test_fake_vm_host_forwarder_loopback_peer_reaches_only_authenticated_launch_route(self):
        self.write_build('linux/arm64')
        with self.provider(mac=True) as runtime:
            expected = {'10.23.0.2', '10.24.0.2', '127.0.0.1'}
            original_run = runtime.run
            def probe(argv, **kwargs):
                if argv[-1] == '--probe':
                    self.assertEqual(expected, runtime.host_bridge.allowed_peers)
                return original_run(argv, **kwargs)
            runtime.run = probe
            self.launcher['start_tic'](self.state)
            self.assertEqual(expected, runtime.host_bridge.allowed_peers)
            response = self.exchange(self.state.tic_handle, f'127.0.0.1:{runtime.host_bridge.port}')
            self.assertEqual('fixture response', response['stdout'])
            probe_index = next(index for index, event in enumerate(runtime.events)
                               if event[0] == 'probe' and event[1][-1] == '--probe')
            self.assertGreater(probe_index, next(index for index, event in enumerate(runtime.events)
                                                if event[0] == 'container'))

    def test_selected_tic_inspection_failure_warns_without_resources_or_fallback(self):
        with self.provider(context=False) as runtime:
            self.assert_tic_unavailable('trusted context inspection failed')
            self.assertIsNone(self.state.tic_handle)
            self.assertEqual([('image', self.state.image), ('image', self.state.sidecar_image)], runtime.events)

    def inspection_document(self):
        return dict(version=1, policy_version=1, native_revision=NATIVE_REVISION,
                    workspace=str(self.state.repository),
                    common_dir=str(self.state.workspaces[0].common_dir),
                    invocation_git_dir=str(self.state.workspaces[0].common_dir))

    def write_inspector(self, source=None):
        # Consumer contract fixture only; optional installed proofs never replace
        # the metadata producer. Configuration lookups below use real host Git.
        system = self.root / 'host-system.config'
        if not system.exists():
            system.write_text('')
        self.git_environment = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
                                'GIT_CONFIG_SYSTEM': str(system), 'PATH': os.defpath}
        if not (self.state.repository / '.git/HEAD').exists():
            subprocess.run(['git', 'init', '--initial-branch=main', str(self.state.repository)],
                           env=self.git_environment, check=True, capture_output=True)
        if source is None:
            source = f'print({json.dumps(self.inspection_document())!r})\n'
        self.broker.write_text(f'#!{sys.executable}\nimport json, os, sys, time\n' + source)
        self.write_build('linux/amd64')
        return self.fixture_build(self.state)

    def test_context_inspects_absolute_installed_broker_once_with_normal_host_config(self):
        observed = self.root / 'inspection-input.json'
        configuration = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
                         'GIT_CONFIG_SYSTEM': str(self.root / 'system.config'),
                         'GIT_CONFIG_GLOBAL': str(self.root / 'global.config'),
                         'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'user.name',
                         'GIT_CONFIG_VALUE_0': 'Effective Override',
                         'GIT_CONFIG_PARAMETERS': "'meta.namespace=normal-override'",
                         'GIT_INDEX_FILE': str(self.root / 'unused-index'),
                         'GIT_SHALLOW_FILE': str(self.root / 'unused-shallow'),
                         'GIT_CEILING_DIRECTORIES': str(self.root),
                         'GIT_DISCOVERY_ACROSS_FILESYSTEM': '1', 'PATH': os.defpath}
        Path(configuration['GIT_CONFIG_SYSTEM']).write_text('')
        Path(configuration['GIT_CONFIG_GLOBAL']).write_text('[user]\nemail = host@example.invalid\n')
        routing = {key: str(self.root / 'wrong-repository') for key in (
            'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_OBJECT_DIRECTORY',
            'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_NAMESPACE')}
        keys = [*configuration, *routing]
        build = self.write_inspector(
            f'keys = {keys!r}\n'
            f'with open({str(observed)!r}, "x") as stream:\n'
            '    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(),\n'
            '               "stdin": sys.stdin.read(),\n'
            '               "environment": {key: os.environ.get(key) for key in keys}}, stream)\n'
            f'print({json.dumps(self.inspection_document())!r})\n')
        with mock.patch.dict(os.environ, configuration | routing, clear=True), mock.patch.object(
                subprocess, 'Popen', wraps=subprocess.Popen) as children:
            value = self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
        self.assertEqual(4, children.call_count)
        self.assertEqual([
            ['git', f'--git-dir={self.state.workspaces[0].common_dir}', 'config', '--null', '--get', key]
            for key in ('user.name', 'user.email', 'meta.namespace')],
            [call.args[0] for call in children.call_args_list[1:]])
        for call in children.call_args_list:
            self.assertEqual(subprocess.DEVNULL, call.kwargs['stdin'])
            self.assertEqual(self.state.repository, call.kwargs['cwd'])
        self.assertEqual({'user_name': 'Effective Override', 'user_email': 'host@example.invalid',
                          'namespace': 'normal-override'}, value)
        captured = json.loads(observed.read_text())
        self.assertEqual(['inspect-context', '--workspace', str(self.state.repository),
                          '--common-dir', str(self.state.workspaces[0].common_dir)], captured['argv'])
        self.assertEqual(str(self.state.repository), captured['cwd'])
        self.assertEqual('', captured['stdin'])
        for key, value in configuration.items():
            self.assertEqual(value, captured['environment'][key], key)
        for key in routing:
            self.assertIsNone(captured['environment'][key], key)

    def test_context_real_host_git_system_xdg_global_includes_worktree_onbranch_and_overrides(self):
        build = self.write_inspector()
        environment = self.git_environment
        def check(name, email, namespace, extra=None):
            with mock.patch.dict(os.environ, environment | (extra or {}), clear=True):
                self.assertEqual({'user_name': name, 'user_email': email, 'namespace': namespace},
                                 self.launcher['inspect_tic_context'](build, self.state.workspaces[0]))
        check('unknown', 'unknown', 'meta')
        Path(environment['GIT_CONFIG_SYSTEM']).write_text(
            '[user]\nname = System\nemail = system@example.invalid\n[meta]\nnamespace = system\n')
        check('System', 'system@example.invalid', 'system')
        xdg = Path(environment['XDG_CONFIG_HOME']) / 'git/config'
        xdg.parent.mkdir(parents=True)
        xdg.write_text('[user]\nname = XDG\nemail = xdg@example.invalid\n[meta]\nnamespace = xdg\n')
        check('XDG', 'xdg@example.invalid', 'xdg')
        included = self.root / 'included.config'
        included.write_text('[user]\nname = Included Global\nemail = global@example.invalid\n'
                            '[meta]\nnamespace = global\n')
        branch = self.root / 'branch.config'
        (self.home / '.gitconfig').write_text(
            f'[include]\npath = {included}\n[includeIf "onbranch:main"]\npath = {branch}\n')
        check('Included Global', 'global@example.invalid', 'global')
        common = self.state.workspaces[0].common_dir
        with (common / 'config').open('a') as stream:
            stream.write('[user]\nemail = local@example.invalid\n[extensions]\nworktreeConfig = true\n')
        check('Included Global', 'local@example.invalid', 'global')
        (common / 'config.worktree').write_text('[meta]\nnamespace = worktree\n')
        check('Included Global', 'local@example.invalid', 'worktree')
        branch.write_text('[user]\nname = On Branch\n')
        check('On Branch', 'local@example.invalid', 'worktree')
        count = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'meta.namespace',
                 'GIT_CONFIG_VALUE_0': 'count'}
        check('On Branch', 'local@example.invalid', 'count', count)
        check('On Branch', 'local@example.invalid', 'parameters',
              count | {'GIT_CONFIG_PARAMETERS': "'meta.namespace=parameters'"})
        selected = self.root / 'selected.config'
        selected.write_text('[user]\nname = Selected\nemail = selected@example.invalid\n'
                            '[meta]\nnamespace = selected\n')
        check('Selected', 'local@example.invalid', 'worktree', {'GIT_CONFIG_GLOBAL': str(selected)})
        check('Selected', 'selected@example.invalid', 'selected', {'GIT_CONFIG': str(selected)})

    def test_context_real_git_uses_linked_invocation_worktree_and_onbranch_config(self):
        self.write_inspector()
        environment = self.git_environment
        subprocess.run(['git', '-C', str(self.state.repository), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', '-c', 'core.hooksPath=/dev/null',
                        'commit', '--allow-empty', '-m', 'fixture'], env=environment,
                       check=True, capture_output=True)
        linked = self.root / 'linked'
        subprocess.run(['git', '-C', str(self.state.repository), 'worktree', 'add', '-b', 'linked',
                        str(linked)], env=environment, check=True, capture_output=True)
        common = self.state.workspaces[0].common_dir
        invocation = common / 'worktrees/linked'
        with (common / 'config').open('a') as stream:
            stream.write('[user]\nname = Common Author\n[extensions]\nworktreeConfig = true\n')
        (common / 'config.worktree').write_text('[meta]\nnamespace = main-worktree\n')
        (invocation / 'config.worktree').write_text('[meta]\nnamespace = linked-worktree\n')
        branch = self.root / 'linked-branch.config'
        branch.write_text('[user]\nemail = linked-branch@example.invalid\n')
        (self.home / '.gitconfig').write_text(f'[includeIf "onbranch:linked"]\npath = {branch}\n')
        document = self.inspection_document() | {'workspace': str(linked),
                                                  'invocation_git_dir': str(invocation)}
        build = self.write_inspector(f'print({json.dumps(document)!r})\n')
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual({'user_name': 'Common Author', 'user_email': 'linked-branch@example.invalid',
                              'namespace': 'linked-worktree'}, self.launcher['inspect_tic_context'](
                                  build, SimpleNamespace(host_root=linked, common_dir=common)))

    def test_context_real_git_preserves_absent_empty_whitespace_newline_and_lossy_strings(self):
        build = self.write_inspector()
        global_config = self.home / '.gitconfig'
        with mock.patch.dict(os.environ, self.git_environment, clear=True):
            self.assertEqual({'user_name': 'unknown', 'user_email': 'unknown', 'namespace': 'meta'},
                             self.launcher['inspect_tic_context'](build, self.state.workspaces[0]))
            for values in ({'user_name': '', 'user_email': '', 'namespace': ''},
                           {'user_name': ' \n\t', 'user_email': '\t \n', 'namespace': ' \t  '}):
                with self.subTest(values=values):
                    global_config.write_text(
                        '[user]\nname = ' + json.dumps(values['user_name']) + '\nemail = '
                        + json.dumps(values['user_email']) + '\n[meta]\nnamespace = '
                        + json.dumps(values['namespace']) + '\n')
                    self.assertEqual(values, self.launcher['inspect_tic_context'](
                        build, self.state.workspaces[0]))
            global_config.write_bytes(b'[user]\nname = invalid-\xff\n')
            self.assertEqual('invalid-\ufffd', self.launcher['inspect_tic_context'](
                build, self.state.workspaces[0])['user_name'])

    def test_context_rejects_wrong_fields_types_versions_pin_paths_and_malformed_json(self):
        document = self.inspection_document()
        cases = [b'raw-fixture-secret invalid JSON', b'\xff', b'[]',
                 json.dumps(document).encode('utf-16'), b'[' * 2000 + b']' * 2000,
                 b'{"version":1,' + json.dumps(document).encode()[1:],
                 json.dumps(document | {'user_name': 'obsolete producer value'}).encode(),
                 json.dumps({key: value for key, value in document.items()
                             if key != 'invocation_git_dir'}).encode()]
        alias = self.root / 'git-dir-alias'
        alias.symlink_to(self.state.workspaces[0].common_dir, target_is_directory=True)
        for key, value in (('version', True), ('version', 1.0), ('version', 2),
                           ('policy_version', True), ('policy_version', 2),
                           ('native_revision', '0' * 40), ('native_revision', 1),
                           ('workspace', str(self.root)), ('common_dir', str(self.root)),
                           ('invocation_git_dir', 1), ('invocation_git_dir', 'relative'),
                           ('invocation_git_dir', str(alias)),
                           ('invocation_git_dir', str(self.state.repository) + '//.git'),
                           ('invocation_git_dir', '\0'),
                           ('invocation_git_dir', '\ud800'),
                           ('invocation_git_dir', str(self.root / 'missing'))):
            cases.append(json.dumps(document | {key: value}).encode())
        for output in cases:
            with self.subTest(output=output[:80]):
                build = self.write_inspector(f'sys.stdout.buffer.write({output!r})\n')
                with self.assertRaisesRegex(self.launcher['LauncherError'], 'trusted context') as error:
                    self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
                self.assertNotIn('raw-fixture-secret', str(error.exception))

    def test_context_rejects_nonzero_inspector_even_with_valid_json_and_scrubs_stderr(self):
        build = self.write_inspector(f'print({json.dumps(self.inspection_document())!r})\n'
                                     'print("raw-fixture-secret", file=sys.stderr)\nsys.exit(1)\n')
        with self.assertRaisesRegex(self.launcher['LauncherError'], 'inspection failed') as error:
            self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
        self.assertNotIn('raw-fixture-secret', str(error.exception))

    def test_context_revalidates_executable_and_repository_paths_before_calling_inspector(self):
        marker = self.root / 'inspector-called'
        build = self.write_inspector(f'open({str(marker)!r}, "w").close()\n')
        self.broker.chmod(0o777)
        with self.assertRaisesRegex(LifecycleError, 'ownership/mode/link'):
            self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
        self.assertFalse(marker.exists())
        self.broker.chmod(0o700)
        build = self.write_inspector(f'open({str(marker)!r}, "w").close()\n')
        alias = self.root / 'workspace-alias'
        alias.symlink_to(self.state.repository, target_is_directory=True)
        workspace = SimpleNamespace(host_root=alias, common_dir=self.state.workspaces[0].common_dir)
        with self.assertRaisesRegex(self.launcher['LauncherError'], 'canonical repository paths'):
            self.launcher['inspect_tic_context'](build, workspace)
        self.assertFalse(marker.exists())

    def test_context_accepts_exactly_64_kib_aggregate_output(self):
        output = json.dumps(self.inspection_document()).encode()
        output += b' ' * (65536 - len(output))
        build = self.write_inspector(f'sys.stdout.buffer.write({output!r})\n')
        with mock.patch.dict(os.environ, self.git_environment, clear=True):
            value = self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
        self.assertEqual({'user_name': 'unknown', 'user_email': 'unknown', 'namespace': 'meta'}, value)

    def test_context_rejects_malformed_git_records_and_lookup_errors(self):
        build = self.write_inspector()
        popen = subprocess.Popen
        for status, output in ((0, b''), (0, b'no delimiter'), (0, b'a\0b\0'),
                               (1, b'value\0'), (2, b''), (128, b'raw-fixture-secret')):
            with self.subTest(status=status, output=output):
                processes = []
                def start(argv, **kwargs):
                    if argv[0] == 'git':
                        self.assertEqual(['git', f'--git-dir={self.state.workspaces[0].common_dir}',
                                          'config', '--null', '--get', 'user.name'], argv)
                        self.assertEqual(subprocess.DEVNULL, kwargs['stdin'])
                        argv = [sys.executable, '-c',
                                f'import sys; sys.stdout.buffer.write({output!r}); sys.exit({status})']
                    process = popen(argv, **kwargs)
                    processes.append(process)
                    return process
                with mock.patch.object(subprocess, 'Popen', start):
                    with self.assertRaisesRegex(self.launcher['LauncherError'], 'configuration lookup failed') as error:
                        self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
                self.assertNotIn('raw-fixture-secret', str(error.exception))
                self.assertEqual(2, len(processes))
                self.assertTrue(all(process.poll() is not None and process.stdout.closed for process in processes))

    def test_context_bounds_output_and_overall_deadline_and_reaps_owned_children(self):
        popen = subprocess.Popen
        for mode, source, message in (
                ('output', 'sys.stdout.buffer.write(b"x" * 65537)\nsys.stdout.flush()\ntime.sleep(30)\n',
                 'output limit'),
                ('timeout', 'time.sleep(30)\n', 'timed out'),
                ('aggregate', 'time.sleep(2)\n' + f'print({json.dumps(self.inspection_document())!r})\n',
                 'timed out')):
            with self.subTest(mode=mode):
                build = self.write_inspector(source)
                processes = []
                def start(argv, **kwargs):
                    if mode == 'aggregate' and argv[0] == 'git':
                        argv = [sys.executable, '-c',
                                'import sys,time; time.sleep(3); sys.stdout.buffer.write(b"v\\0")']
                    process = popen(argv, **kwargs)
                    processes.append(process)
                    return process
                started = time.monotonic()
                with mock.patch.object(subprocess, 'Popen', start):
                    with self.assertRaisesRegex(self.launcher['LauncherError'], message):
                        self.launcher['inspect_tic_context'](build, self.state.workspaces[0])
                self.assertEqual(4 if mode == 'aggregate' else 1, len(processes))
                self.assertTrue(all(process.poll() is not None and process.stdout.closed for process in processes))
                self.assertLess(time.monotonic() - started, 15 if mode != 'output' else 5)

    def test_context_bounds_aggregate_git_values(self):
        build = self.write_inspector()
        value = 'x' * 22000
        (self.home / '.gitconfig').write_text(
            f'[user]\nname = {value}\nemail = {value}\n[meta]\nnamespace = {value}\n')
        with mock.patch.dict(os.environ, self.git_environment, clear=True):
            with self.assertRaisesRegex(self.launcher['LauncherError'], 'output limit'):
                self.launcher['inspect_tic_context'](build, self.state.workspaces[0])

    def test_macho_and_wrong_elf_architecture_reject_before_host_child(self):
        for header in (b'\xcf\xfa\xed\xfe' + bytes(60),
                       b'\x7fELF\x02\x01' + bytes(12) + (183).to_bytes(2, 'little') + bytes(44)):
            with self.subTest(header=header[:6]):
                self.write_build('linux/amd64', header)
                with self.provider() as runtime:
                    self.assert_tic_unavailable('matching Linux ELF')
                    self.assertFalse(runtime.present)
                    self.assertIsNone(self.state.tic_handle.process)
                    self.assertEqual({}, self.state.tic_environment)

    def test_manifest_provider_architecture_mismatch_rejects(self):
        self.write_build('linux/arm64')
        with self.provider() as runtime:
            self.assert_tic_unavailable('provider platform')
            self.assertFalse(runtime.present)

    def test_unsafe_installed_executable_disables_tic_before_child_or_relay_effect(self):
        self.native.chmod(0o777)
        with self.provider() as runtime:
            self.assert_tic_unavailable('ownership/mode/link')
            self.assertIsNone(self.state.tic_handle)
            self.assertEqual([('image', self.state.image), ('image', self.state.sidecar_image)], runtime.events)

    def test_failed_transport_readiness_cleans_child_relay_and_staged_client(self):
        for failure in ('listener', 'authenticated-help'):
            with self.subTest(failure=failure), self.provider() as runtime:
                if failure == 'listener':
                    runtime.listener_status = 125
                else:
                    runtime.probe_status = 125
                self.assert_tic_unavailable('readiness failed')
                self.assertFalse(runtime.present)
                self.assertIsNone(self.state.tic_handle.process)
                self.assertEqual({}, self.state.tic_environment)
                mount = next(item[1] for item in runtime.events if item[0] == 'container')
                staged = Path(mount[mount.index('--mount') + 1].split('src=')[1].split(',')[0])
                self.assertFalse(staged.exists())
                calls = [event[1][-1] for event in runtime.events if event[0] == 'probe']
                self.assertEqual(['--probe'] if failure == 'listener' else ['--probe', '--help'], calls)

    def test_image_platform_failure_is_required_before_child_or_relay_start(self):
        with self.provider() as runtime:
            runtime.verify_builder_image = mock.Mock(side_effect=RuntimeError('wrong platform'))
            with self.assertRaisesRegex(self.launcher['LauncherError'], 'images matching'):
                self.launcher['start_tic'](self.state)
            self.assertIsNone(self.state.tic_handle)
            self.assertFalse(runtime.present)

    def test_staged_copy_failure_cleans_private_output(self):
        original = self.globals['shutil'].copyfile
        for name in ('guest-ti', 'tic_relay.py', 'host_tcp_bridge.py'):
            with self.subTest(source=name):
                def fail(source, destination):
                    original(source, destination)
                    if Path(source).name == name:
                        raise OSError('owned copy failure')
                with self.provider() as runtime, mock.patch('shutil.copyfile', side_effect=fail):
                    self.assert_tic_unavailable('owned copy failure')
                    self.assertFalse(runtime.present)
                    self.assertEqual([], list((runtime.host.state / 'scratch').glob('sandbox-tic-client-*')))

    def test_each_staged_bind_rejection_cleans_before_broker_or_relay_start(self):
        self.write_build('linux/arm64')
        for rejected in ('ti', 'relay'):
            with self.subTest(rejected=rejected), self.provider(mac=True) as runtime:
                def reject(sources):
                    self.assertEqual(['ti', 'relay'], [Path(path).name for path, _ in sources])
                    self.assertEqual([False, False], [writable for _, writable in sources])
                    self.assertTrue(all(Path(path).exists() for path, _ in sources))
                    raise ValueError(f'rejected staged {rejected}')
                runtime.host.check_binds.side_effect = reject
                with mock.patch.object(self.globals['TicBrokerLaunch'], 'start') as start, \
                        mock.patch.object(self.globals['TicBrokerLaunch'], 'start_bridge') as bridge:
                    self.assert_tic_unavailable(f'rejected staged {rejected}')
                runtime.host.check_binds.assert_called_once()
                start.assert_not_called()
                bridge.assert_not_called()
                self.assertFalse(runtime.present)
                self.assertIsNone(self.state.tic_handle.process)
                self.assertFalse(any(event[0] in ('network', 'container', 'probe', 'environment')
                                     for event in runtime.events))
                self.assertEqual([], list((runtime.host.state / 'scratch').glob('sandbox-tic-client-*')))

    def test_snapshot_address_failures_never_publish_peers_environment_or_readiness(self):
        for network in ('link', 'egress'):
            for address in (None, '', '999.1.1.1'):
                with self.subTest(network=network, address=address), self.provider() as runtime:
                    networks = {'codex-tic-link-first': {'IPAddress': '10.23.0.2'},
                                'codex-tic-egress-first': {'IPAddress': '10.24.0.2'}}
                    name = f'codex-tic-{network}-first'
                    if address is None:
                        del networks[name]
                    else:
                        networks[name]['IPAddress'] = address
                    runtime.inspect_container = mock.Mock(return_value={
                        'NetworkSettings': {'Networks': networks}})
                    runtime.network_addresses = lambda container, names: (
                        ContainerRuntime.network_addresses(runtime, container, names))
                    self.assert_tic_unavailable('not permitted' if address else 'not attached')
                    runtime.inspect_container.assert_called_once_with('codex-tic-first')
                    self.assertEqual(set(), runtime.host_bridge.allowed_peers)
                    self.assertFalse(any(event[0] in ('probe', 'environment') for event in runtime.events))
                    self.assertFalse(runtime.present)
                    self.assertIsNone(self.state.tic_handle.process)

    def test_missing_endpoint_never_attaches_guest(self):
        with self.provider() as runtime:
            runtime.network_address = lambda container, network: ''
            self.assert_tic_unavailable('incomplete network')
            self.assertEqual({}, self.state.tic_environment)
            self.assertFalse(runtime.present)

    def test_shared_join_runs_tic_without_resolvers_and_continues_without_failed_tic(self):
        self.state.deferred_signal = None
        self.state.proxy_lock = SimpleNamespace(shared=True)
        empty = ('validate_repository', 'prepare_host_session', 'acquire_lock', 'load_accepted_session',
                 'recover_relays', 'stage_skills', 'agent_repository_mounts', 'prepare_host_pi_resources',
                 'register_tmux_pane', 'ensure_network', 'prepare_gateway', 'attach_proxies')
        replacements = {name: mock.Mock(return_value=[]) for name in empty}
        forbidden = {name: mock.Mock(side_effect=AssertionError('join invoked ' + name)) for name in (
            'load_repository_policy', 'resolve_model_image', 'resolve_sidecar_image', 'prepare_declared_images')}
        agent = mock.Mock(return_value=19)
        with self.provider() as runtime, mock.patch.dict(self.globals, replacements | forbidden | {'run_agent': agent}):
            self.assertEqual(19, self.launcher['execute'](self.state))
            handle = self.state.tic_handle
            self.assertEqual(LifecycleState.ATTACHED, handle.lifecycle.state)
            arguments = agent.call_args.args[1]
            self.assertIn('codex-tic-link-first', arguments)
            self.assertIn('dst=/opt/agent-tools/bin/ti,readonly', ' '.join(arguments))
            handle.stop()
            agent.reset_mock()
            self.state.suffix = 'failed-join'
            runtime.probe_status = 125
            with mock.patch('sys.stderr', new_callable=io.StringIO) as warning:
                self.assertEqual(19, self.launcher['execute'](self.state))
            self.assertIn('TicGit unavailable for this session', warning.getvalue())
            agent.assert_called_once()
            arguments = agent.call_args.args[1]
            self.assertNotIn('codex-tic-link-failed-join', arguments)
            self.assertNotIn('dst=/opt/agent-tools/bin/ti', ' '.join(arguments))
            self.assertEqual({}, self.state.tic_environment)
            self.assertIsNone(self.state.tic_handle.process)
            self.assertFalse(runtime.present)
        for resolver in forbidden.values():
            resolver.assert_not_called()

    def test_guest_worker_receives_only_current_launch_token_in_private_env_file(self):
        self.state.pi_model_session_id = 'fixture-session'
        self.state.codex_container = 'worker'
        self.state.container_repository = Path('/src/workspace')
        self.state.handoff_origin = None
        fresh = {'SANDBOX_TIC_TOKEN': 'fresh-fixture-token', 'SANDBOX_TIC_ENDPOINT': '10.0.0.2:2225'}
        self.state.tic_environment = fresh
        @contextmanager
        def workload(*args, **kwargs):
            yield SimpleNamespace(poll=lambda: 17)
        with self.provider() as runtime:
            runtime.workload = workload
            runtime.inspect_image = lambda image: image
            command = ['docker', 'run', '--name', 'worker', self.state.image]
            with mock.patch.dict('os.environ', {'SANDBOX_TIC_TOKEN': 'stale-token',
                                                'SANDBOX_TIC_ENDPOINT': 'old-endpoint'}), mock.patch.dict(
                    self.globals, {'prepare_agent_mountpoints': mock.Mock(),
                                   'host_pi_resource_paths': lambda state: {str(state.repository): '/src/workspace'},
                                   'build_agent_command': mock.Mock(return_value=command),
                                   'keychain_environment': lambda state: {}}):
                with self.assertRaisesRegex(self.launcher['LauncherError'], 'worker exited'):
                    self.launcher['run_agent'](self.state, [])
            environments = [event[1] for event in runtime.events if event[0] == 'environment']
            self.assertEqual([fresh], environments)
            self.assertNotIn('fresh-fixture-token', ' '.join(command))

    def install_test_bundle(self, *, provision=False):
        # Installation and permissions changes are confined to this fixture's
        # disposable prefix. No host installation or provider acceptance.
        shutil.rmtree(self.install)
        self.install = self.home / '.cache/codex-sandbox/tic'
        self.globals['resolved_tic_build'] = self.real_resolver
        def writable_install_cleanup():
            # Only this test's disposable installation is changed. Register
            # before the fallible installer so partial read-only output cannot
            # prevent TemporaryDirectory cleanup; never follow directory links.
            if self.install.is_symlink():
                return
            for directory, _, _ in os.walk(self.install, followlinks=False):
                path = Path(directory)
                if not path.is_symlink():
                    path.chmod(0o700)
        self.addCleanup(writable_install_cleanup)
        from tic_artifact import resolve_bundle, configure_native_source
        if provision:
            # Exercise ordinary cold provisioning with the real pinned builder,
            # not just a local-bundle override. The source file is in temp HOME.
            configure_native_source(self.home, Path(os.environ['TIC_LAUNCHER_TEST_NATIVE_REPOSITORY']))
            with self.provider():
                build = self.real_resolver(self.state)
            self.manifest = build.native_executable.parent.parent / 'manifest.json'
        else:
            self.manifest = resolve_bundle(self.install, 'linux/amd64', [self.state.repository],
                                          mock.Mock(side_effect=AssertionError('explicit fixture bundle')),
                                          local_bundle=Path(os.environ['TIC_LAUNCHER_TEST_BUNDLE']))
        system = self.root / 'system.gitconfig'
        system.write_text('')
        environment = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
                       'GIT_CONFIG_SYSTEM': str(system), 'PATH': os.defpath}
        subprocess.run(['git', 'init', '--initial-branch=main', str(self.state.repository)],
                       check=True, capture_output=True, env=environment)
        return environment

    @unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('TIC_LAUNCHER_TEST_BUNDLE'),
                         'set TIC_LAUNCHER_TEST_BUNDLE to a reviewed local Linux bundle')
    def test_installed_warm_start_never_hashes_artifacts_or_opens_store(self):
        environment = self.install_test_bundle()
        with mock.patch.dict(os.environ, environment, clear=True), self.provider(context=False), mock.patch.object(
                hashlib, 'file_digest', side_effect=AssertionError('runtime file hashing')):
            self.assertTrue(self.launcher['start_tic'](self.state))
            self.assertIsNotNone(self.state.tic_handle.process)
            self.assertFalse((self.state.workspaces[0].common_dir / 'git-meta.sqlite').exists())

    @unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('TIC_LAUNCHER_TEST_BUNDLE'),
                         'set TIC_LAUNCHER_TEST_BUNDLE to a reviewed local Linux bundle')
    def test_installed_context_absent_defaults_and_literal_empty_whitespace_values(self):
        environment = self.install_test_bundle()
        with self.provider():
            build = self.real_resolver(self.state)
        global_config = self.home / '.gitconfig'
        with mock.patch.dict(os.environ, environment, clear=True):
            for values in ({'user_name': 'unknown', 'user_email': 'unknown', 'namespace': 'meta'},
                           {'user_name': '', 'user_email': '', 'namespace': ''},
                           {'user_name': '  ', 'user_email': '\t ', 'namespace': ' \t  '}):
                with self.subTest(values=values):
                    if values['user_name'] != 'unknown':
                        global_config.write_text(
                            '[user]\nname = ' + json.dumps(values['user_name']) + '\nemail = '
                            + json.dumps(values['user_email']) + '\n[meta]\nnamespace = '
                            + json.dumps(values['namespace']) + '\n')
                    self.assertEqual(values, self.launcher['inspect_tic_context'](
                        build, self.state.workspaces[0]))
                    self.assertFalse((self.state.workspaces[0].common_dir / 'git-meta.sqlite').exists())

    @unittest.skipUnless(sys.platform.startswith('linux') and os.environ.get('TIC_LAUNCHER_TEST_BUNDLE'),
                         'set TIC_LAUNCHER_TEST_BUNDLE to a reviewed local Linux bundle')
    def test_installed_native_client_broker_roundtrip_with_local_fake_provider_transport(self):
        # Real installed inspection, broker, staged client/wrapper and native;
        # only provider effects are replaced with owned local TCP transport.
        environment = self.install_test_bundle(provision=bool(os.environ.get('TIC_LAUNCHER_TEST_NATIVE_REPOSITORY')))
        Path(environment['GIT_CONFIG_SYSTEM']).write_text(
            '[user]\nname = System Author\nemail = system@example.invalid\n'
            '[meta]\nnamespace = system-fixture\n')
        xdg_config = Path(environment['XDG_CONFIG_HOME']) / 'git/config'
        xdg_config.parent.mkdir(parents=True)
        xdg_config.write_text('[user]\nname = XDG Author\nemail = xdg@example.invalid\n'
                              '[meta]\nnamespace = xdg-fixture\n')
        global_config = self.home / '.gitconfig'
        global_config.write_text('[user]\nname = Global Author\nemail = global-author@example.invalid\n'
                                 '[meta]\nnamespace = global-fixture\n')
        for key, value in (('user.name', 'Local Launch Author'),
                           ('meta.namespace', 'local-fixture'), ('extensions.worktreeConfig', 'true')):
            subprocess.run(['git', '-C', str(self.state.repository), 'config', '--local', key, value],
                           env=environment, check=True, capture_output=True)
        (self.state.workspaces[0].common_dir / 'config.worktree').write_text(
            '[meta]\nnamespace = worktree-fixture\n')
        expected = {'user_name': 'Local Launch Author', 'user_email': 'global-author@example.invalid',
                    'namespace': 'worktree-fixture'}
        database = self.state.workspaces[0].common_dir / 'git-meta.sqlite'
        self.assertFalse(database.exists())
        relay = None
        with mock.patch.dict(os.environ, environment, clear=True), self.provider(context=False) as runtime:
            original_run = self.globals['run']
            original_remove = self.globals['remove_owned_resource']
            def launch_relay(argv, **kwargs):
                nonlocal relay
                result = original_run(argv, **kwargs)
                mounts = [argv[index + 1] for index, value in enumerate(argv) if value == '--mount']
                client_mount = next(value for value in mounts if 'dst=/opt/agent-tools/bin/ti,' in value)
                relay_mount = next(value for value in mounts if 'dst=/trusted/tic,' in value)
                runtime.client = Path(client_mount.split('src=')[1].split(',')[0])
                script = Path(relay_mount.split('src=')[1].split(',')[0]) / 'tic_relay.py'
                self.assert_delayed_python_response(runtime.client, script)
                relay = LocalPythonRelay(script, int(argv[argv.index('--target-port') + 1]))
                return result
            def remove(runtime_arg, kind, name, owner, **kwargs):
                if name == self.state.tic_resources.container and relay is not None:
                    relay.stop()
                original_remove(runtime_arg, kind, name, owner, **kwargs)
            @contextmanager
            def environment_file(values):
                runtime.probe_environment = values
                yield []
            def client(argv, values=None):
                environment = dict(values or self.state.tic_environment)
                environment['SANDBOX_TIC_ENDPOINT'] = f'127.0.0.1:{relay.port}'
                return subprocess.run([str(runtime.client), *argv], env=environment,
                                      cwd=self.state.repository, capture_output=True, text=True, timeout=15)
            def native_new_with_observed_identity(title, frozen):
                # No wrapper or diagnostic command: briefly block our own store
                # writer, then inspect the actual owned native executable. Name
                # and namespace are not exposed by admitted command JSON.
                lock = sqlite3.connect(database)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    try:
                        lock.execute('BEGIN IMMEDIATE')
                        result = pool.submit(client, ['new', '--title', title, '--json'])
                        handle = self.state.tic_handle
                        observed = None
                        deadline = time.monotonic() + 2
                        while observed is None and time.monotonic() < deadline:
                            tasks = Path(f'/proc/{handle.process.pid}/task')
                            for children in tasks.glob('*/children'):
                                try:
                                    pids = children.read_text().split()
                                except FileNotFoundError:
                                    continue
                                for pid in pids:
                                    process = Path('/proc') / pid
                                    try:
                                        if (process / 'exe').resolve(strict=True) != handle.build.native_executable:
                                            continue
                                        observed = dict(record.split(b'=', 1) for record in
                                                        (process / 'environ').read_bytes().split(b'\0') if record)
                                    except FileNotFoundError:
                                        continue
                            if observed is None:
                                time.sleep(0.01)
                        self.assertIsNotNone(observed, 'owned native child was not observed')
                        self.assertEqual(b'3', observed[b'GIT_CONFIG_COUNT'])
                        for index, (field, key) in enumerate((('user_name', 'user.name'),
                                                              ('user_email', 'user.email'),
                                                              ('namespace', 'meta.namespace'))):
                            self.assertEqual(key.encode(), observed[f'GIT_CONFIG_KEY_{index}'.encode()])
                            self.assertEqual(frozen[field].encode(), observed[f'GIT_CONFIG_VALUE_{index}'.encode()])
                        self.assertNotIn(b'GIT_CONFIG_PARAMETERS', observed)
                        self.assertNotIn(b'SANDBOX_TIC_TOKEN', observed)
                    finally:
                        lock.rollback()
                        lock.close()
                    return result.result(timeout=15)
            runtime.environment_file = environment_file
            runtime.run = lambda argv, **kwargs: (relay.probe() if argv[-1] == '--probe'
                                                  else client(argv[-1:], runtime.probe_environment))
            runtime.network_address = lambda container, network: '127.0.0.1'
            with mock.patch.dict(self.globals, {'run': launch_relay, 'remove_owned_resource': remove}):
                try:
                    self.launcher['start_tic'](self.state)
                    self.assertFalse(database.exists(), 'inspection/readiness/help must not open SQLite')
                    self.assertEqual(expected, {key: self.state.tic_handle.config[key] for key in expected})
                    denied = client(['new', '--title', 'forbidden author override',
                                     '--author', 'guest-author@example.invalid'])
                    self.assertNotEqual(0, denied.returncode)
                    self.assertFalse(database.exists(), 'guest author overrides must reject before native open')
                    # Native execution freezes accepted values; later normal host
                    # configuration edits must not change this launch's author.
                    global_config.write_text(
                        '[user]\nname = Changed Global Author\nemail = changed@example.invalid\n'
                        '[meta]\nnamespace = changed-global-fixture\n')
                    created = client(['new', '--title', 'launcher roundtrip', '--id-only'])
                    self.assertEqual(0, created.returncode, created.stderr)
                    ticket = created.stdout.strip()
                    self.assertTrue(ticket)
                    commented = client(['comment', '--ticket', ticket,
                                        'through staged client and fixed transport'])
                    self.assertEqual(0, commented.returncode, commented.stderr)
                    observed = native_new_with_observed_identity('observed frozen configuration', expected)
                    self.assertEqual(0, observed.returncode, observed.stderr)
                    self.assertEqual(expected['user_email'], json.loads(observed.stdout)['created_by'])
                    guest_file = self.root / 'guest-only-body.txt'
                    guest_file.write_text('content collected by the staged guest client\n')
                    writeup = client(['writeup', 'new', '--title', 'guest file roundtrip',
                                      '--file', str(guest_file)])
                    self.assertEqual(0, writeup.returncode, writeup.stderr)
                    writeups = client(['writeup', 'list'])
                    self.assertEqual(0, writeups.returncode, writeups.stderr)
                    self.assertIn('guest file roundtrip', writeups.stdout)
                    listed = client(['list', '--json'])
                    self.assertEqual(0, listed.returncode, listed.stderr)
                    self.assertIn('launcher roundtrip', listed.stdout)
                    self.assertIn(expected['user_email'], listed.stdout)
                    history = client(['history', '--ticket', ticket, '--json'])
                    self.assertEqual(0, history.returncode, history.stderr)
                    self.assertIn(expected['user_email'], history.stdout)
                    self.assertNotIn('changed@example.invalid', history.stdout)
                    installed = self.real_resolver(self.state)
                    human = subprocess.run([str(installed.native_executable), 'list', '--json'],
                                           cwd=self.state.repository, env=environment,
                                           capture_output=True, text=True, timeout=15)
                    self.assertEqual(0, human.returncode, human.stderr)
                    self.assertIn('launcher roundtrip', human.stdout)
                    self.assertTrue(database.is_file())
                    self.state.tic_handle.stop()
                    self.assertTrue(database.is_file(), 'launch cleanup must retain tickets')
                    self.assertFalse(runtime.present)
                    # Exercise literal values through this same real installed
                    # route, not just the inspection dictionary. Remove earlier
                    # fixture-local overrides so these globals are authoritative.
                    for key in ('user.name', 'meta.namespace'):
                        subprocess.run(['git', '-C', str(self.state.repository), 'config', '--local',
                                        '--unset-all', key], env=environment, check=True, capture_output=True)
                    (self.state.workspaces[0].common_dir / 'config.worktree').write_text('')
                    for label, literal in (
                            ('empty', {'user_name': '', 'user_email': '', 'namespace': ''}),
                            ('whitespace', {'user_name': '  ', 'user_email': '\t ', 'namespace': ' \t  '})):
                        with self.subTest(literal=label):
                            global_config.write_text(
                                '[user]\nname = ' + json.dumps(literal['user_name']) + '\nemail = '
                                + json.dumps(literal['user_email']) + '\n[meta]\nnamespace = '
                                + json.dumps(literal['namespace']) + '\n')
                            self.state.suffix = 'literal-' + label
                            self.launcher['start_tic'](self.state)
                            self.assertEqual(literal, {key: self.state.tic_handle.config[key] for key in literal})
                            global_config.write_text(
                                '[user]\nname = Later Author\nemail = later@example.invalid\n'
                                '[meta]\nnamespace = later-namespace\n')
                            created = native_new_with_observed_identity('literal ' + label, literal)
                            self.assertEqual(0, created.returncode, created.stderr)
                            ticket_json = json.loads(created.stdout)
                            self.assertEqual(literal['user_email'], ticket_json['created_by'])
                            history = client(['history', '--ticket', ticket_json['id'], '--json'])
                            self.assertEqual(0, history.returncode, history.stderr)
                            entries = json.loads(history.stdout)
                            self.assertTrue(entries)
                            self.assertTrue(all(entry['email'] == literal['user_email'] for entry in entries))
                            self.state.tic_handle.stop()
                            self.assertFalse(runtime.present)
                            self.assertTrue(database.is_file())
                finally:
                    if relay is not None:
                        relay.stop()

    def assert_delayed_python_response(self, client, script):
        # Wire 2 admits the complete length-delimited request while the client
        # write side remains open. Preserve a >1s delayed framed response and its
        # normal EOF through the unchanged staged Python TCP transport.
        errors = []
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            server.settimeout(5)
            def respond():
                try:
                    while True:
                        with server.accept()[0] as connection:
                            connection.settimeout(5)
                            with connection.makefile('rb') as stream:
                                header = stream.read(4)
                                if not header:  # TCP-only listener probes.
                                    continue
                                self.assertEqual(4, len(header))
                                size = struct.unpack('!I', header)[0]
                                self.assertLessEqual(size, 8 * 1024 * 1024)
                                data = stream.read(size)
                                self.assertEqual(size, len(data))
                            request = json.loads(data)
                            self.assertEqual('owned-delay-token', request['token'])
                            self.assertEqual({'version': 2, 'command': 'tic', 'argv': ['--help'], 'stdin': ''},
                                             request['request'])
                            time.sleep(1.25)
                            frame = json.dumps({'version': 2, 'exit': 0, 'stdout': 'delayed complete response',
                                                'stderr': ''}).encode()
                            connection.sendall(struct.pack('!I', len(frame)) + frame)
                            break
                except BaseException as error:
                    errors.append(error)
            worker = threading.Thread(target=respond)
            worker.start()
            delayed = None
            try:
                delayed = LocalPythonRelay(script, server.getsockname()[1])
                started = time.monotonic()
                result = subprocess.run([str(client), '--help'], env={
                    'SANDBOX_TIC_ENDPOINT': f'127.0.0.1:{delayed.port}',
                    'SANDBOX_TIC_TOKEN': 'owned-delay-token'},
                    capture_output=True, text=True, timeout=8)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('delayed complete response', result.stdout)
                self.assertGreaterEqual(time.monotonic() - started, 1)
            finally:
                if delayed is not None:
                    delayed.stop()
                worker.join(timeout=6)
            self.assertFalse(worker.is_alive())
            if errors:
                raise errors[0]

    def test_independent_owning_launches_do_not_adopt_endpoint_or_token(self):
        with self.provider():
            self.launcher['start_tic'](self.state)
            first = self.state.tic_handle
            token, address = first.token, first.address
            self.state.suffix = 'second'
            self.launcher['start_tic'](self.state)
            second = self.state.tic_handle
            self.assertNotEqual(token, second.token)
            self.assertNotEqual(address, second.address)
            self.assertEqual(first.config['common_dir'], second.config['common_dir'])
            first.stop()
            self.assertEqual('fixture response', self.exchange(second)['stdout'])


if __name__ == '__main__':
    unittest.main()
