"""Guest transport preserves shell arguments, binary stdin, and failure status."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lima.docker_host import DockerHost


class GuestTransportTest(unittest.TestCase):
    def test_remote_command_keeps_arguments_and_protocol_separate(self):
        host = object.__new__(DockerHost)
        arguments = ['', "quoted ' and \"", '$(exit 99)', 'line\nbreak', '--flag']
        argv = host.guest_argv({'socket': '/vm/sock/docker.sock', 'instance': 'sandbox-host-docker'},
                               sys.executable, ROOT / 'tests/guest_command_fixture.py', *arguments)
        result = subprocess.run(['sh', '-c', argv[-1]], input=b'\x00\xff\nprotocol',
                                capture_output=True, env={**os.environ, 'SHELL': '/bin/bash'})
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'argv': arguments, 'cwd': '/private/tmp'
                         if sys.platform == 'darwin' else '/tmp', 'stdin': '00ff0a70726f746f636f6c'})

    def test_unfinished_setup_uses_lima(self):
        host = object.__new__(DockerHost)
        self.assertEqual(host.guest_argv({'instance': 'sandbox-host-docker'}, 'true'),
                         ['limactl', 'shell', '--workdir', '/tmp', 'sandbox-host-docker', 'true'])


if __name__ == '__main__':
    unittest.main()
