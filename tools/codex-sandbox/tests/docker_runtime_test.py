"""Rootless Docker identity, command preservation, and firewall regressions."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from lima.docker_host import DockerHost
from lima.docker import nftables
from sandbox_runtime import RuntimeError

spec = importlib.util.spec_from_file_location('docker_policy', ROOT / 'lima/docker/policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def backend():
    runtime = object.__new__(Docker)
    runtime.host = Mock(state=Path('/owned'))
    runtime.record = {'client': sys.executable, 'socket': '/owned/docker.sock'}
    runtime.recovery = False
    return runtime


class DockerRuntimeTest(unittest.TestCase):
    def test_environment_file_needs_no_guest_share_and_is_private_until_cleanup(self):
        runtime = backend()
        runtime.host.check_bind.side_effect = AssertionError('host file checked in guest')
        with self.assertRaisesRegex(ValueError, 'launch failed'):
            with runtime.environment_file({'TOKEN': 'literal $value'}) as arguments:
                path = Path(arguments[1])
                self.assertFalse(path.is_relative_to(runtime.host.state))
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text(), 'TOKEN=literal $value\n')
                raise ValueError('launch failed')
        self.assertFalse(path.exists())
        with self.assertRaisesRegex(RuntimeError, 'cannot be represented'):
            with runtime.environment_file({'TOKEN': 'line\nbreak'}):
                self.fail('invalid environment staged')

    def test_owned_helpers_use_installed_declaration_without_executable_builders(self):
        import owned_images
        runtime = backend()
        runtime.bake = Mock(return_value={'jj': 'repository-image'})
        runtime.run_builders = Mock(return_value={})
        command = next(path for path, name in owned_images.COMMANDS.items() if name == 'jj')
        with patch('bake.resolve', return_value={'jj': 'installed-image'}) as resolve:
            prepared = runtime.prepare_images(Path('/repository'), {
                'trusted': {'image-command': [command]}, 'untrusted': {'image-target': 'jj'}})
        self.assertEqual(prepared.proxies, {'trusted': 'installed-image', 'untrusted': 'repository-image'})
        self.assertEqual(resolve.call_args.args[:3], (runtime, owned_images.ROOT, ['jj']))
        runtime.run_builders.assert_called_once_with({})
        self.assertIsNone(owned_images.target([command, 'extra']))
        self.assertIsNone(owned_images.target(['.agents/sandbox/jj-proxy-image']))

    def test_machine_lookup_leaves_configuration_drift_to_the_audit(self):
        host = object.__new__(DockerHost)
        machine = {'config': {}}
        host.machine_identity = Mock(return_value=machine)
        record = {'config_digest': 'different configuration'}
        self.assertIs(host.machine(record), machine)
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            host.verify(record)

    def test_new_runtime_checks_identity_and_readiness_once(self):
        host = Mock()
        host.record.return_value = {'phase': 'ready'}
        with patch('docker_runtime.DockerHost', return_value=host), patch.object(Docker, 'verify_identity') as identity:
            Docker(Path('/owned'))
            identity.assert_called_once_with()
            host.verify_runtime.assert_called_once_with(host.record.return_value)
            host.verify.assert_not_called()
            host.verify_runtime.side_effect = ValueError('readiness has not completed')
            with self.assertRaisesRegex(ValueError, 'readiness'):
                Docker(Path('/owned'))
            host.verify_runtime.reset_mock()
            Docker(Path('/owned'), recovery=True)
            host.verify_runtime.assert_not_called()

    def test_ready_host_does_not_audit_policy_until_doctor(self):
        host = object.__new__(DockerHost)
        host.state = Path('/owned')
        host.runtime_epoch = Mock(return_value='a' * 32)
        host.verify = Mock()
        host.verify_runtime({})
        host.verify.assert_not_called()
        host.doctor({})
        host.verify.assert_called_once_with({})
        host.verify.side_effect = ValueError('policy drift')
        host.verify_runtime({})
        with self.assertRaisesRegex(ValueError, 'policy drift'):
            host.doctor({})
        host.verify.side_effect = None
        host.runtime_epoch.side_effect = ['a' * 32, 'b' * 32]
        with self.assertRaisesRegex(ValueError, 'restarted during doctor'):
            host.doctor({})

    def test_admitted_runtime_does_not_recheck_service_for_commands_or_metadata(self):
        runtime = backend()
        runtime.verify = Mock(side_effect=AssertionError('repeated service check'))
        runtime.verify_identity = Mock(side_effect=AssertionError('repeated identity check'))
        runtime.client_argv = lambda arguments: arguments
        for command in (['run', 'image'], ['exec', 'owned', 'command'], ['network', 'create', 'new'],
                        ['inspect', 'owned'], ['wait', 'owned']):
            self.assertEqual(runtime.argv(command), command)
        with patch('docker_runtime.inspect_docker', return_value={}):
            self.assertEqual(runtime.image_metadata('image'), {})
            self.assertEqual(runtime.inspect_container('owned'), {})

    def test_preparation_reuses_bake_references_and_validates_executable_results_once(self):
        runtime = backend()
        runtime.bake = Mock(return_value={'base': 'base@digest', 'bug': 'bug@digest'})
        auth = 'sha256:' + 'a' * 64
        helper = 'sha256:' + 'b' * 64
        runtime.run_builders = Mock(return_value={
            'auth': subprocess.CompletedProcess(['auth'], 0, auth + '\n'),
            'proxy:jj': subprocess.CompletedProcess(['jj'], 0, helper + '\n')})
        rendezvous = threading.Barrier(2)
        def inspect(value):
            rendezvous.wait(timeout=2)
            return value
        runtime.builder_image = Mock(side_effect=inspect)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / '.agents/sandbox').mkdir(parents=True)
            (repo / '.agents/sandbox/bake').touch()
            prepared = runtime.prepare_images(repo, {
                'bug': {'image-target': 'bug'}, 'jj': {'image-command': ['jj']}},
                include_base=True, auth_builder=(['auth'], repo))
        self.assertEqual(prepared.base, 'base@digest')
        self.assertEqual(prepared.auth, auth)
        self.assertEqual(prepared.proxies, {'bug': 'bug@digest', 'jj': helper})
        self.assertCountEqual([call.args[0] for call in runtime.builder_image.call_args_list], [auth, helper])
        runtime.bake.assert_called_once_with(repo, ['base', 'bug'])
        self.assertEqual(runtime.run_builders.call_args.args[0],
                         {'auth': (['auth'], repo), 'proxy:jj': (['jj'], repo)})

    def test_preparation_rejects_multiline_builder_output(self):
        runtime = backend()
        runtime.bake = Mock(return_value={})
        runtime.run_builders = Mock(return_value={
            'proxy:jj': subprocess.CompletedProcess(['jj'], 0, 'sha256:' + 'a' * 64 + '\n\n')})
        runtime.builder_image = Mock()
        with self.assertRaisesRegex(ValueError, 'exactly one immutable image hash'):
            runtime.prepare_images(Path('/unused'), {'jj': {'image-command': ['jj']}})
        runtime.builder_image.assert_not_called()

    def test_relay_creation_checks_new_bridge_without_repeating_admission(self):
        runtime = backend()
        runtime.record['firewall'] = 'nftables'
        events = []
        runtime.verify = Mock(side_effect=lambda: events.append('ready'))
        runtime.client_argv = lambda arguments: arguments
        runtime.guest = Mock(side_effect=lambda *a, **kw: events.append('bridge policy'))
        with patch('subprocess.run', side_effect=lambda *a, **kw: events.append('create')) as run:
            runtime.create_relay_network('owned', internal=True, owner='a' * 32)
            self.assertEqual(events, ['create', 'bridge policy'])
            runtime.verify.assert_not_called()

    def test_container_identity_uses_one_live_snapshot_for_labels_and_image(self):
        runtime = backend()
        runtime.verify_identity = Mock()
        image = Mock(config='sha256:expected')
        raw = {'Image': image.config, 'Config': {'Image': 'untrusted-tag', 'Labels': {'owner': 'ours'}}}
        with patch('docker_runtime.inspect_docker', return_value=raw) as inspect:
            self.assertTrue(runtime.container_matches_image('owned', image, labels={'owner': 'ours'}))
            runtime.verify_identity.assert_not_called()
            inspect.assert_called_once_with('/owned/docker.sock', '/containers/owned/json',
                                            ['docker', 'inspect', 'owned'])
            raw['Config']['Labels']['owner'] = 'another'
            self.assertFalse(runtime.container_matches_image('owned', image, labels={'owner': 'ours'}))
            raw['Config']['Labels']['owner'] = 'ours'
            raw['Image'] = 'sha256:another'
            self.assertFalse(runtime.container_matches_image('owned', image, labels={'owner': 'ours'}))
            inspect.reset_mock()
            runtime.recovery = True
            runtime.verify_identity.side_effect = ValueError('engine replaced')
            with self.assertRaisesRegex(ValueError, 'engine replaced'):
                runtime.inspect_container('owned')
            inspect.assert_not_called()

    def test_independent_builders_overlap_and_keep_their_own_output(self):
        runtime = backend()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, str(ROOT / 'tests/builder_barrier_fixture.py'), str(root)]
            results = runtime.run_builders({'first': ([*command, 'first', 'second'], root),
                                            'second': ([*command, 'second', 'first'], root)})
            self.assertEqual({name: result.stdout for name, result in results.items()},
                             {'first': 'first\n', 'second': 'second\n'})

    def test_successful_builder_waits_for_child_to_finish_its_reference(self):
        runtime = backend()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, str(ROOT / 'tests/builder_barrier_fixture.py'), str(root)]
            results = runtime.run_builders({'first': ([*command, 'child-first', 'second'], root),
                                            'second': ([*command, 'second', 'child-first'], root)})
            self.assertEqual(results['first'].stdout, 'child-first\n')
            self.assertEqual(results['second'].stdout, 'second\n')
            result = runtime.run_builder([*command, 'child-single', 'child-single'], cwd=root)
            self.assertEqual(result.stdout, 'child-single\n')

    def test_single_builder_preserves_capture_streaming_and_status_on_worker_thread(self):
        runtime = backend()
        for capture in (False, True):
            for name, status in (('reference', 0), ('fail', 7)):
                with self.subTest(capture=capture, status=status), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    command = [sys.executable, str(ROOT / 'tests/builder_barrier_fixture.py'),
                               str(root), name, name]
                    with tempfile.TemporaryFile(mode='w+') as stream, \
                            patch('docker_runtime.sys.stderr', stream), ThreadPoolExecutor() as worker:
                        result = worker.submit(runtime.run_builder, command, cwd=root, capture=capture).result(timeout=5)
                        self.assertEqual(result.returncode, status)
                        self.assertEqual(result.args, command)
                        output = 'reference\n' if status == 0 else ''
                        self.assertEqual(result.stdout, output if capture else None)
                        stream.seek(0)
                        self.assertEqual(stream.read(), '' if capture else output)

    def test_failed_builder_stops_its_running_peer_before_returning(self):
        runtime = backend()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, str(ROOT / 'tests/builder_barrier_fixture.py'), str(root)]
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                runtime.run_builders({'first': ([*command, 'fail', 'wait'], root),
                                      'second': ([*command, 'wait', 'fail'], root)})
            self.assertEqual(failure.exception.returncode, 7)
            pid = (root / 'wait').read_text()
            listing = subprocess.run(['ps', '-axo', 'pid=,stat='], check=True,
                                     capture_output=True, text=True).stdout.splitlines()
            self.assertFalse(any(fields[0] == pid and not fields[1].startswith('Z')
                                 for line in listing if len(fields := line.split()) == 2))

    def test_cancel_builder_stops_nested_build_and_lock_waiter(self):
        class Cancelled(Exception):
            pass
        for waiting, batched in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(waiting=waiting, batched=batched), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime = backend()
                runtime.host.state = root
                sibling = root / 'sibling'
                sibling.mkdir()
                with (root / 'build-output.lock').open('a') as lock:
                    if waiting:
                        fcntl.flock(lock, fcntl.LOCK_EX)
                    marker = root / ('ready' if waiting else 'child')
                    done = threading.Event()
                    def interrupt():
                        deadline = time.monotonic() + 5
                        while not done.wait(0.01) and time.monotonic() < deadline:
                            if (marker.exists() and marker.read_text() and
                                    (not batched or (sibling / 'child').exists())):
                                os.kill(os.getpid(), signal.SIGTERM)
                                return
                    def cancelled(signum, frame):
                        raise Cancelled('builder cancelled')
                    handler = signal.signal(signal.SIGTERM, cancelled)
                    thread = threading.Thread(target=interrupt)
                    thread.start()
                    started = time.monotonic()
                    try:
                        with self.assertRaisesRegex(Cancelled, 'builder cancelled'):
                            command = [sys.executable, str(ROOT / 'tests/builder_cancel_fixture.py'), 'build']
                            if batched:
                                runtime.run_builders({'first': ([*command, str(root)], root),
                                                      'second': ([*command, str(sibling)], sibling)})
                            else:
                                runtime.run_builder([*command, str(root)])
                        self.assertLess(time.monotonic() - started, 5)
                        listing = subprocess.run(['ps', '-axo', 'pid=,stat='], capture_output=True,
                                                 text=True, check=True).stdout.splitlines()
                        for path in (root / 'ready', root / 'child', sibling / 'ready', sibling / 'child'):
                            if path.exists():
                                pid = path.read_text()
                                self.assertFalse(any(fields[0] == pid and not fields[1].startswith('Z')
                                                     for line in listing if len(fields := line.split()) == 2))
                    finally:
                        done.set()
                        thread.join()
                        signal.signal(signal.SIGTERM, handler)
                        # A failing cancellation assertion must not leave the
                        # fixture alive, including a child in an escaped session.
                        for path in (root / 'ready', root / 'child', sibling / 'ready', sibling / 'child'):
                            if path.exists() and path.read_text():
                                try:
                                    os.kill(int(path.read_text()), signal.SIGKILL)
                                except ProcessLookupError:
                                    pass

    def test_build_platform_comes_from_the_recorded_engine(self):
        runtime = backend()
        runtime.verify_identity = Mock()
        with patch('docker_runtime.inspect_docker', return_value={'OSType': 'linux', 'Architecture': 'aarch64'}) as info:
            self.assertEqual(runtime.build_platform(), 'linux/arm64')
            info.assert_called_once_with('/owned/docker.sock', '/info', ['docker', 'info'])
            runtime.verify_identity.assert_not_called()

    def test_failed_builder_reaps_plugin_after_wrapper_already_exited(self):
        for batched in (False, True):
            with self.subTest(batched=batched), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pidfile = root / 'pid'
                runtime = backend()
                runtime.host.state = root
                command = [sys.executable, str(ROOT / 'tests/builder_orphan_fixture.py'), str(pidfile), '7']
                try:
                    if batched:
                        with self.assertRaises(subprocess.CalledProcessError) as raised:
                            runtime.run_builders({'failed': (command, root)})
                        self.assertEqual(raised.exception.returncode, 7)
                    else:
                        result = runtime.run_builder(command, capture=False)
                        self.assertEqual(result.returncode, 7)
                    pid = pidfile.read_text()
                    listing = subprocess.run(['ps', '-axo', 'pid=,stat='], check=True,
                                             capture_output=True, text=True).stdout.splitlines()
                    self.assertFalse(any(fields[0] == pid and not fields[1].startswith('Z')
                                         for line in listing if len(fields := line.split()) == 2))
                finally:
                    if pidfile.exists():
                        try:
                            os.kill(int(pidfile.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_failed_build_reports_operation_without_dumping_client_configuration(self):
        runtime = backend()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime.host.state = root
            runtime.argv = Mock(return_value=['/usr/bin/env', '-uDOCKER_HOST', '/private/client',
                                              '--host', 'unix:///private/socket', 'buildx', 'build'])
            with patch.object(runtime, 'run_builder', return_value=subprocess.CompletedProcess([], 7)), \
                    patch.dict(os.environ, {'CODEX_SANDBOX_BUILDER_GROUP': '0'}):
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    runtime.build('test', root / 'Dockerfile', root)
            self.assertEqual(raised.exception.returncode, 7)
            self.assertEqual(str(raised.exception),
                             'sandbox image build failed (exit 7); see BuildKit output above')

    def test_cleanup_cannot_mutate_an_unverified_engine(self):
        runtime = backend()
        runtime.verify_identity = Mock(side_effect=ValueError('engine identity changed'))
        runtime.host.verify_runtime.side_effect = ValueError('engine identity changed')
        for command in (['rm', '-f', 'agent'], ['network', 'rm', 'link'],
                        ['volume', 'rm', 'proxy']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'engine identity'):
                    runtime.run(command)
                run.assert_not_called()

    def test_recovery_allows_only_identity_checked_inspection_and_cleanup(self):
        runtime = backend()
        runtime.verify_identity = Mock()
        runtime.recovery = True
        runtime.host.verify_runtime.side_effect = ValueError('damaged firewall')
        for command in (['rm', '-f', 'owned'], ['network', 'rm', 'owned'], ['volume', 'rm', 'owned']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                runtime.run(command)
                run.assert_called_once()
        for command in (['run', 'image'], ['exec', 'owned', 'command'], ['network', 'create', 'new']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'cleanup only'):
                    runtime.run(command)
                run.assert_not_called()
        runtime.recovery = True
        runtime.host.verify_runtime.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'cleanup only'):
            runtime.argv(['run', 'image'])

    @patch('docker_runtime.inspect_docker')
    def test_credential_wrapper_preserves_image_entrypoint_and_default_command(self, query):
        runtime = backend()
        query.return_value = {'Config': {'Entrypoint': ['/custom-agent', '--offline'], 'Cmd': ['default']}}
        self.assertEqual(runtime.agent_command('image', []), ['/custom-agent', '--offline', 'default'])
        self.assertEqual(runtime.agent_command('image', ['request']), ['/custom-agent', '--offline', 'request'])

    @patch('docker_runtime.inspect_docker')
    def test_image_digest_must_belong_to_inspected_content(self, query):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        config = 'sha256:' + '2' * 64
        layer = 'sha256:' + '3' * 64
        query.return_value = {'Id': config, 'RepoDigests': ['agent@' + content], 'RootFS': {'Layers': [layer]}}
        image = runtime.inspect_image('agent:tag')
        self.assertEqual((image.reference, image.config), ('agent@' + content, config))
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            runtime.inspect_image('other@' + content)

    @patch('docker_runtime.inspect_docker')
    def test_launch_reuses_immutable_image_metadata_but_refreshes_tags(self, query):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        query.return_value = {'Id': 'sha256:' + '2' * 64, 'RepoTags': ['agent:built'],
            'RepoDigests': ['agent@' + content], 'RootFS': {'Layers': ['sha256:' + '3' * 64]},
            'Config': {'Entrypoint': ['pi'], 'Cmd': ['--offline']}}
        image = runtime.inspect_image('agent:built')
        self.assertEqual(runtime.inspect_image(image.reference), image)
        self.assertEqual(runtime.agent_command(image.reference, []), ['pi', '--offline'])
        query.assert_called_once()
        runtime.inspect_image('agent:built')
        self.assertEqual(query.call_count, 2)

    @patch('docker_runtime.inspect_docker')
    def test_local_base_keeps_its_tag_and_digest_for_buildkit(self, query):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        query.return_value = {'Id': 'sha256:' + '2' * 64, 'RepoTags': ['agent:built'],
                             'RepoDigests': ['agent@' + content], 'RootFS': {'Layers': ['sha256:' + '3' * 64]}}
        reference = runtime.inspect_image('agent:built').reference
        self.assertEqual(reference, 'agent:built@' + content)
        self.assertEqual(runtime.inspect_image(reference).reference, reference)

    @patch('docker_runtime.inspect_docker')
    def test_image_reference_preserves_requested_repository_and_tag(self, query):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        query.return_value = {'Id': 'sha256:' + '2' * 64, 'RepoTags': ['codex-sandbox-bake:temporary', 'codex-sandbox:cache'],
             'RepoDigests': ['codex-sandbox-bake@' + content, 'codex-sandbox@' + content],
             'RootFS': {'Layers': ['sha256:' + '3' * 64]}}
        self.assertEqual(runtime.inspect_image('codex-sandbox:cache').reference, 'codex-sandbox:cache@' + content)

    def test_explicit_shares_do_not_add_home_or_expose_control_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            host = DockerHost(root / 'state')
            with patch('lima.docker_host.machines', return_value={'sandbox-host-docker-test': {}}):
                # Reaches the existing-VM rejection: read-only sharing did not
                # silently add an overlapping home share or expose state.
                with self.assertRaisesRegex(ValueError, 'existing Docker VM'):
                    host.setup('sandbox-host-docker-test', read=[str(ROOT)])
                with self.assertRaisesRegex(ValueError, 'control directory'):
                    host.setup('sandbox-host-docker-test', write=[str(root)])


class FirewallTest(unittest.TestCase):
    def test_reference_cancellation_reaps_child_after_wrapper_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            done = threading.Event()

            def cancel():
                while not done.wait(0.01):
                    if pidfile.exists() and pidfile.read_text().strip():
                        os.kill(os.getpid(), signal.SIGTERM)
                        return

            thread = threading.Thread(target=cancel)
            thread.start()
            started = time.monotonic()
            try:
                with patch.object(nftables, 'run', return_value='owned-origin'):
                    with self.assertRaisesRegex(Exception, 'verification interrupted'):
                        nftables.reference([sys.executable, str(ROOT / 'tests/builder_orphan_fixture.py'),
                                            str(pidfile), '0'], 'unused')
                self.assertLess(time.monotonic() - started, 5)
                pid = pidfile.read_text()
                listing = subprocess.run(['ps', '-axo', 'pid=,stat='], check=True,
                                         capture_output=True, text=True).stdout.splitlines()
                self.assertFalse(any(fields[0] == pid and not fields[1].startswith('Z')
                                     for line in listing if len(fields := line.split()) == 2))
            finally:
                done.set()
                thread.join()
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_native_rule_order_and_coverage_survive_normalization(self):
        rules = [{'rule': {'family': 'inet', 'table': 'codex_sandbox', 'chain': 'forward',
                           'expr': [expression]}} for expression in ({'return': None}, {'reject': None})]
        canonical = lambda entries: nftables.canonical(json.dumps({'nftables': entries}))
        self.assertEqual(canonical(rules), canonical([
            {'metainfo': {'version': '1.0.9'}},
            *[{'rule': {**entry['rule'], 'handle': index}} for index, entry in enumerate(rules)]]))
        for changed in (rules[:1], rules[::-1], [*rules, rules[0]],
                        [{'rule': {**rules[0]['rule'], 'expr': [{'accept': None}]}}, rules[1]]):
            with self.subTest(changed=changed):
                self.assertNotEqual(canonical(rules), canonical(changed))

    def test_unrecorded_native_helper_is_rejected_before_execution(self):
        files = {'nftables.py', 'network.nft', 'docker-daemon.json', 'network-policy.json'}
        for missing in files:
            record = {'generation': 'test', 'firewall': 'nftables',
                      'files': dict.fromkeys(files - {missing}, 'digest')}
            with self.subTest(missing=missing), patch.object(policy.os, 'getuid', return_value=1000), \
                    patch.dict(os.environ, SANDBOX_GENERATION='test'), patch.object(policy, 'firewall') as install:
                with self.assertRaisesRegex(ValueError, 'not recorded'):
                    policy.verify(record)
                install.assert_not_called()

    def test_rootless_service_is_not_ready_during_post_start_policy_install(self):
        host = object.__new__(DockerHost)
        host.machine = Mock(return_value={'sshConfigFile': '/owned/ssh.config', 'hostname': 'lima-owned'})
        with patch('lima.docker_host.command') as query:
            query.return_value.stdout = 'ActiveState=activating\nSubState=start-post\nInvocationID=' + 'a' * 32
            with self.assertRaisesRegex(ValueError, 'readiness'):
                host.runtime_epoch({})
            query.return_value.stdout = 'ActiveState=active\nSubState=running\nInvocationID=' + 'b' * 32
            self.assertEqual('b' * 32, host.runtime_epoch({}))
            self.assertEqual(('ssh', '-F', '/owned/ssh.config', '-T', 'lima-owned'),
                             query.call_args.args[:5])
            query.return_value.stdout = 'ActiveState=active\nSubState=running\nInvocationID='
            with self.assertRaisesRegex(ValueError, 'readiness'):
                host.runtime_epoch({})
            query.side_effect = subprocess.CalledProcessError(255, ['ssh'])
            with self.assertRaises(subprocess.CalledProcessError):
                host.runtime_epoch({})
            query.reset_mock()
            host.machine.side_effect = ValueError('VM identity changed')
            with self.assertRaisesRegex(ValueError, 'identity'):
                host.runtime_epoch({})
            query.assert_not_called()


if __name__ == '__main__':
    unittest.main()
