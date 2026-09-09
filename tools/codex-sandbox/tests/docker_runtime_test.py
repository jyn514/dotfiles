"""Rootless Docker identity, command preservation, and firewall regressions."""

import importlib.util
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
    runtime.record = {'client': '/real/docker', 'socket': '/owned/docker.sock'}
    return runtime


class DockerRuntimeTest(unittest.TestCase):
    def test_bake_failure_reaps_plugin_after_wrapper_already_exited(self):
        for status in ('0', '1'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'scratch').mkdir()
                pidfile = root / 'pid'
                runtime = backend()
                runtime.host.state = root
                runtime.argv = Mock(return_value=[sys.executable, str(ROOT / 'tests/bake_orphan_fixture.py'),
                                                 str(pidfile), status])
                try:
                    with self.assertRaises((FileNotFoundError, subprocess.CalledProcessError)):
                        runtime.bake({'test': {'context': str(root), 'dockerfile': str(root / 'Dockerfile')}})
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
            (root / 'scratch').mkdir()
            runtime.host.state = root
            runtime.argv = Mock(return_value=['/usr/bin/env', '-uDOCKER_HOST', '/private/client',
                                              '--host', 'unix:///private/socket', 'buildx', 'bake'])
            process = Mock()
            process.wait.return_value = 7
            with patch('subprocess.Popen', return_value=process), patch('docker_runtime.stop_build') as stop:
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    runtime.bake({'base': {'context': str(root)}})
            self.assertEqual(raised.exception.returncode, 7)
            self.assertEqual(str(raised.exception),
                             'sandbox image build failed (exit 7); see BuildKit output above')
            stop.assert_called_once_with(process)

    def test_cleanup_cannot_mutate_an_unverified_engine(self):
        runtime = backend()
        runtime.host.verify_runtime.side_effect = ValueError('engine identity changed')
        for command in (['rm', '-f', 'agent'], ['network', 'rm', 'link'],
                        ['volume', 'rm', 'proxy'], ['exec', 'proxy', 'command']):
            with self.subTest(command=command), patch('subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'engine identity'):
                    runtime.run(command)
                run.assert_not_called()

    def test_credential_wrapper_preserves_image_entrypoint_and_default_command(self):
        runtime = backend()
        runtime.run = Mock(return_value=Mock(stdout=json.dumps([
            {'Config': {'Entrypoint': ['/custom-agent', '--offline'], 'Cmd': ['default']}}])))
        self.assertEqual(runtime.agent_command('image', []), ['/custom-agent', '--offline', 'default'])
        self.assertEqual(runtime.agent_command('image', ['request']), ['/custom-agent', '--offline', 'request'])

    def test_image_digest_must_belong_to_inspected_content(self):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        config = 'sha256:' + '2' * 64
        layer = 'sha256:' + '3' * 64
        runtime.run = Mock(return_value=Mock(stdout=json.dumps([
            {'Id': config, 'RepoDigests': ['agent@' + content], 'RootFS': {'Layers': [layer]}}])))
        image = runtime.inspect_image('agent:tag')
        self.assertEqual((image.reference, image.config), ('agent@' + content, config))
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            runtime.inspect_image('other@' + content)

    def test_local_base_keeps_its_tag_and_digest_for_buildkit(self):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        runtime.run = Mock(return_value=Mock(stdout=json.dumps([
            {'Id': 'sha256:' + '2' * 64, 'RepoTags': ['agent:built'],
             'RepoDigests': ['agent@' + content], 'RootFS': {'Layers': ['sha256:' + '3' * 64]}}])))
        reference = runtime.inspect_image('agent:built').reference
        self.assertEqual(reference, 'agent:built@' + content)
        self.assertEqual(runtime.inspect_image(reference).reference, reference)

    def test_image_reference_preserves_requested_repository_and_tag(self):
        runtime = backend()
        content = 'sha256:' + '1' * 64
        runtime.run = Mock(return_value=Mock(stdout=json.dumps([
            {'Id': 'sha256:' + '2' * 64, 'RepoTags': ['codex-sandbox-bake:temporary', 'codex-sandbox:cache'],
             'RepoDigests': ['codex-sandbox-bake@' + content, 'codex-sandbox@' + content],
             'RootFS': {'Layers': ['sha256:' + '3' * 64]}}])))
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
                        nftables.reference([sys.executable, str(ROOT / 'tests/bake_orphan_fixture.py'),
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
        host.machine = Mock()
        host.guest = Mock(return_value=Mock(stdout='ActiveState=activating\nSubState=start-post\nInvocationID=' + 'a' * 32))
        with self.assertRaisesRegex(ValueError, 'readiness'):
            host.runtime_epoch({})


if __name__ == '__main__':
    unittest.main()
