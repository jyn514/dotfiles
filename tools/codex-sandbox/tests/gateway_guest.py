"""Exercise editor authentication, SSH, and isolation through a real gateway."""
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
from urllib.parse import urlparse

if '--refused-editor' in sys.argv:
    address, port = os.environ['CODEX_SANDBOX_EDITOR_ADDRESS'].rsplit(':', 1)
    with socket.create_connection((address, int(port)), timeout=5) as connection:
        try:
            assert not connection.recv(1), 'refused upstream returned data'
        except ConnectionResetError:
            pass
else:
    runpy.run_path(str(Path(__file__).with_name('lima_editor_probe.py')))
host = urlparse(os.environ['CONTAINER_HOST'])
subprocess.run(['ssh', '-i', os.environ['CONTAINER_SSHKEY'], '-p', str(host.port),
                '-o', 'HostKeyAlias=agent-podman', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile=' + os.environ['AGENT_PODMAN_KNOWN_HOSTS'],
                '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                f'{host.username}@{host.hostname}', 'true'], check=True, timeout=10)
for address, port in [(os.environ['OTHER_GATEWAY_IP'], 2222),
                      (os.environ['OTHER_GATEWAY_IP'], 2223),
                      ('host.lima.internal', int(os.environ['HOST_EDITOR_PORT']))]:
    try:
        connection = socket.create_connection((address, port), timeout=1)
    except OSError:
        continue
    connection.close()
    raise AssertionError(f'agent bypassed gateway isolation: {address}:{port}')
print('Gateway SSH authentication and cross-session isolation passed.')
