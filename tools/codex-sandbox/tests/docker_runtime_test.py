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
    def test_relay_creation_checks_readiness_then_bridge_policy(self):
        runtime = backend()
        runtime.record['firewall'] = 'nftables'
        events = []
        runtime.verify = Mock(side_effect=lambda: events.append('ready'))
        runtime.client_argv = lambda arguments: arguments
        runtime.guest = Mock(side_effect=lambda *a, **kw: events.append('bridge policy'))
        with patch('subprocess.run', side_effect=lambda *a, **kw: events.append('create')) as run:
            runtime.create_relay_network('owned', internal=True, owner='a' * 32)
            self.assertEqual(events, ['ready', 'create', 'bridge policy'])
            events.clear()
            run.reset_mock()
            runtime.verify.side_effect = ValueError('not ready')
            with self.assertRaisesRegex(ValueError, 'not ready'):
                runtime.create_relay_network('owned', internal=True, owner='a' * 32)
            run.assert_not_called()
            self.assertEqual(events, [])

    def test_container_identity_uses_one_live_snapshot_for_labels_and_image(self):
        runtime = backend()
        runtime.verify_identity = Mock()
        image = Mock(config='sha256:expected')
        raw = {'Image': image.config, 'Config': {'Image': 'untrusted-tag', 'Labels': {'owner': 'ours'}}}
        with patch('docker_runtime.inspect_docker', return_value=raw) as inspect:
            self.assertTrue(runtime.container_matches_image('owned', image, labels={'owner': 'ours'}))
            runtime.verify_identity.assert_called_once_with()
            inspect.assert_called_once_with('/owned/docker.sock', '/containers/owned/json',
                                            ['docker', 'inspect', 'owned'])
            raw['Config']['Labels']['owner'] = 'another'
            self.assertFalse(runtime.container_matches_image('owned', image, labels={'owner': 'ours'}))
            raw['Config']['Labels']['owner'] = 'ours'
            raw['Image'] = 'sha256:another'
            self.assertFalse(runtime.container_matches_image('owned', image, labels={'owner': 'ours'}))
            inspect.reset_mock()
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

    def test_builder_base_image_ids_resolve_locally_without_rewriting_other_arguments(self):
        runtime = backend()
        image = 'sha256:' + 'a' * 64
        runtime.inspect_image = Mock(return_value=Mock(reference='base:key@sha256:manifest'))
        arguments = ['buildx', 'build', '--build-arg', 'BASE_IMAGE=' + image,
                     '--build-arg=BASE_IMAGE=' + image, '--build-arg', 'OTHER=' + image,
                     '--build-arg', 'BASE_IMAGE=alpine:3.22', '.']
        expected = [*arguments]
        expected[3] = 'BASE_IMAGE=base:key@sha256:manifest'
        expected[4] = '--build-arg=BASE_IMAGE=base:key@sha256:manifest'
        self.assertEqual(runtime.builder_arguments(arguments), expected)
        self.assertEqual(arguments[3], 'BASE_IMAGE=' + image)

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
                        ['volume', 'rm', 'proxy'], ['exec', 'proxy', 'command']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'engine identity'):
                    runtime.run(command)
                run.assert_not_called()

    def test_policy_damage_blocks_admission_but_not_identity_checked_cleanup(self):
        runtime = backend()
        runtime.verify_identity = Mock()
        runtime.host.verify_runtime.side_effect = ValueError('damaged firewall')
        for command in (['rm', '-f', 'owned'], ['network', 'rm', 'owned'], ['volume', 'rm', 'owned']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                runtime.run(command)
                run.assert_called_once()
        for command in (['run', 'image'], ['exec', 'owned', 'command'], ['network', 'create', 'new']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'damaged firewall'):
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
