#!/usr/bin/env python3
"""Exercise context selection with the real Docker CLI and a fixture VM record."""

from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'tools/codex-sandbox/lima/docker_host.py'
spec = importlib.util.spec_from_file_location('docker_host', SOURCE)
docker_host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docker_host)


@unittest.skipUnless(shutil.which('docker'), 'requires the Docker CLI')
class DockerContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.client = shutil.which('docker')
        self.record = {'client': self.client, 'instance': 'fixture',
                       'socket': str(self.directory / 'first socket.sock')}
        self.host = mock.Mock()
        self.host.locked.return_value = nullcontext()
        self.host.setup.return_value = self.record
        self.environment = mock.patch.dict(os.environ, DOCKER_CONFIG=str(self.directory / 'docker'))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT'):
            previous = os.environ.pop(key, None)
            if previous is not None:
                self.addCleanup(os.environ.__setitem__, key, previous)

    def setup_vm(self, select=True):
        arguments = [str(SOURCE), 'setup']
        if select:
            arguments.extend(['--default-context', 'lima'])
        with mock.patch.object(sys, 'argv', arguments), \
                mock.patch.object(docker_host, 'DockerHost', return_value=self.host):
            docker_host.main()

    def docker(self, *arguments):
        return subprocess.run([self.client, *arguments], check=True,
                              text=True, capture_output=True).stdout

    def test_setup_selects_and_rerun_updates_the_authoritative_socket(self):
        self.setup_vm()
        self.assertEqual('lima', self.docker('context', 'show').strip())
        self.record['socket'] = str(self.directory / 'second socket.sock')
        self.setup_vm()
        context = json.loads(self.docker('context', 'inspect', 'lima'))[0]
        self.assertEqual('unix://' + self.record['socket'], context['Endpoints']['docker']['Host'])
        self.assertEqual('lima', self.docker('context', 'show').strip())

    def test_failed_provisioning_leaves_default_unchanged(self):
        self.host.setup.side_effect = ValueError('provisioning failed')
        with self.assertRaisesRegex(ValueError, 'provisioning failed'):
            self.setup_vm()
        self.assertEqual('default', self.docker('context', 'show').strip())

    def test_direct_setup_without_flag_leaves_default_unchanged(self):
        self.setup_vm(select=False)
        self.assertEqual('default', self.docker('context', 'show').strip())

    def test_failed_context_update_does_not_select_it(self):
        with mock.patch.object(docker_host, 'command', side_effect=[
                subprocess.CompletedProcess([], 0, stdout=''),
                subprocess.CalledProcessError(1, ['docker', 'context', 'create'])]):
            with self.assertRaises(subprocess.CalledProcessError):
                self.setup_vm()
        self.assertEqual('default', self.docker('context', 'show').strip())

    def test_setup_sandbox_requests_default_context(self):
        source = (ROOT / 'setup').read_text()
        function = source[source.index('setup_sandbox () {'):source.index('\nsetup_all () {')]
        script = self.directory / 'setup-fixture.sh'
        script.write_text(function + '\nexists() { return 0; }\n'
                          'python3() { printf "%s\\n" "$@"; }\nsetup_sandbox\n')
        result = subprocess.run(['sh', str(script)], check=True, text=True, capture_output=True)
        self.assertEqual(['tools/codex-sandbox/lima/docker_host.py', 'setup',
                          '--default-context', 'lima'], result.stdout.splitlines()[1:])


if __name__ == '__main__':
    unittest.main()
