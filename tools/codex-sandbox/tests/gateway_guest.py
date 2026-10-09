"""Exercise SSH and isolation through a real gateway."""
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

host = urlparse(os.environ['DOCKER_HOST'])
ssh = ['ssh', '-i', os.environ['AGENT_DOCKER_SSHKEY'], '-p', str(host.port),
                '-o', 'HostKeyAlias=agent-docker', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile=' + os.environ['AGENT_DOCKER_KNOWN_HOSTS'],
                '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                f'{host.username}@{host.hostname}']
subprocess.run([*ssh, 'true'], check=True, timeout=10)
info = subprocess.check_output(['docker', 'info', '--format', '{{json .SecurityOptions}}'], text=True)
assert 'name=rootless' in info, info
tag = 'nested-gateway-probe:' + uuid.uuid4().hex
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    repo = root / 'repository with spaces'
    repo.mkdir()
    (repo / 'Dockerfile').write_text(
        "FROM alpine:3.22\nRUN printf 'nested-build-ok' > /result\n")
    subprocess.run(['docker', 'build', '-t', tag, str(repo)], check=True, timeout=120)
    # Keep the pipeline outside the requested repository to exercise staging.
    pipeline = root / 'pipeline.yml'
    pipeline.write_text('steps:\n  shared-engine:\n    image: ' + tag +
                        '\n    pull: false\n    environment:\n'
                        '      NESTED_PROBE:\n        from_secret: nested_probe\n'
                        '    commands:\n'
                        '      - test "$(cat /result)" = nested-build-ok\n'
                        '      - test "$NESTED_PROBE" = forwarded\n')
    try:
        subprocess.run(['woodpecker-cli', 'exec', '--repo-path', str(repo),
                        '--backend-engine=docker', '--repo-trusted-security', str(pipeline)],
                       env=os.environ | {'WOODPECKER_SECRETS': 'nested_probe=forwarded'},
                       check=True, timeout=120)
        pipeline.write_text('steps:\n  cancellation:\n    image: ' + tag +
                            '\n    pull: false\n    commands:\n'
                            '      - echo nested-cancellation-ready\n      - sleep 300\n')
        process = subprocess.Popen(['woodpecker-cli', 'exec', '--repo-path', str(repo),
            '--backend-engine=docker', '--repo-trusted-security', str(pipeline)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = []
        ready = threading.Event()
        def read_output():
            for line in process.stdout:
                output.append(line)
                if 'nested-cancellation-ready' in line:
                    ready.set()
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            assert ready.wait(60), ''.join(output)
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=45) == 143, ''.join(output)
            reader.join(timeout=5)
            run_id = re.search(r'remote run ([a-f0-9]{32})', ''.join(output)).group(1)
            subprocess.run([*ssh, 'test', '!', '-e',
                f'/home/{host.username}/.local/state/agent-docker/woodpecker-runs/{run_id}'],
                check=True, timeout=10)
            deadline = time.monotonic() + 10
            while subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'ancestor=' + tag]).strip():
                assert time.monotonic() < deadline, 'cancelled Woodpecker left its container behind'
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=45)
            reader.join(timeout=5)
            process.stdout.close()
    finally:
        # A failed assertion must still remove only this probe's resources.
        leftovers = subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'ancestor=' + tag],
                                            text=True).split()
        if leftovers:
            subprocess.run(['docker', 'rm', '--force', *leftovers], check=True, timeout=30)
        subprocess.run(['docker', 'image', 'rm', tag], check=True, timeout=30)
print('Agent Docker build, staged Woodpecker secrets, cancellation and cleanup passed.')
for address, port in [(os.environ['OTHER_GATEWAY_IP'], 2222)]:
    try:
        connection = socket.create_connection((address, port), timeout=1)
    except OSError:
        continue
    connection.close()
    raise AssertionError(f'agent bypassed gateway isolation: {address}:{port}')
print('Gateway SSH authentication and cross-session isolation passed.')
