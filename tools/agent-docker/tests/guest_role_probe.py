"""Opt-in guest-root acceptance for the untrusted build role; never run on the host."""
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import uuid


if len(sys.argv) == 3:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=2):
        pass
else:
    installed = Path('/usr/local/share/agent-docker/guest-install.py')
    assert installed.is_file(), 'this probe requires the owned build guest'
    guest = runpy.run_path(str(installed))
    builder = guest['as_builder']
    guest['check']()
    builder('docker', '--host', 'unix:///run/user/1001/docker.sock', 'run', '--rm',
            '--privileged', 'alpine:3.22', 'true', capture_output=True)
    with socket.socket() as canary:
        canary.bind(('127.0.0.1', 0))
        canary.listen(4)
        address, port = canary.getsockname()
        # Prove this destination is live before challenging the UID boundary.
        with socket.create_connection((address, port), timeout=2):
            pass
        try:
            builder('python3', str(Path(__file__).resolve()), address, str(port), capture_output=True)
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('build account reached the live guest-root loopback listener')
    with tempfile.TemporaryDirectory(prefix='agent-build-canary-') as directory:
        root_canary = Path(directory) / 'root-only'
        root_canary.write_bytes(b'guest-root-canary')
        root_canary.chmod(0o600)
        alias = guest['HOME'] / ('.setup-probe-' + uuid.uuid4().hex)
        builder('ln', '-s', str(root_canary), str(alias))
        try:
            try:
                guest['write_builder'](alias, b'overwritten')
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('setup writer followed a build symlink with guest-root authority')
            assert root_canary.read_bytes() == b'guest-root-canary'
            try:
                builder('docker', '--host', 'unix:///run/user/1001/docker.sock', 'run', '--rm',
                        '--privileged', '--mount', f'type=bind,src={root_canary},dst=/probe,readonly',
                        'alpine:3.22', 'cat', '/probe', capture_output=True)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('privileged rootless container read guest-root data')
        finally:
            builder('rm', '-f', '--', str(alias))
    print('build role blocked live loopback, guest-root data and setup symlink escalation')
