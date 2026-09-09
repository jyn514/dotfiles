"""Rootless Docker identity, command preservation, and firewall regressions."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from lima.docker_host import DockerHost
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
    def test_selector_order_is_irrelevant_but_rule_order_and_coverage_are_not(self):
        expected = [['-i', 'cs-public', '-d', '10.0.0.0/8', '-j', 'REJECT'],
                    ['-i', 'csl+', '-j', 'REJECT']]
        lines = ['-A CS-FORWARD -d 10.0.0.0/8 -i cs-public -j REJECT --reject-with icmp-port-unreachable',
                 '-A CS-FORWARD -i csl+ -j REJECT']
        with patch.object(policy, 'run', return_value='\n'.join(lines)):
            policy.check_chain([], 'iptables', 'CS-FORWARD', expected)
        for changed in (lines[:1], lines[::-1], [*lines, '-A CS-FORWARD -j ACCEPT']):
            with self.subTest(changed=changed), patch.object(policy, 'run', return_value='\n'.join(changed)):
                with self.assertRaisesRegex(ValueError, 'differs'):
                    policy.check_chain([], 'iptables', 'CS-FORWARD', expected)

    def test_rootless_service_is_not_ready_during_post_start_policy_install(self):
        host = object.__new__(DockerHost)
        host.machine = Mock()
        host.guest = Mock(return_value=Mock(stdout='ActiveState=activating\nSubState=start-post\nInvocationID=' + 'a' * 32))
        with self.assertRaisesRegex(ValueError, 'readiness'):
            host.runtime_epoch({})


if __name__ == '__main__':
    unittest.main()
