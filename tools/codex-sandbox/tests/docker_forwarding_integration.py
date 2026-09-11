"""Exercise production forwarding using an owned disposable bug-manifest repository.

Pass a cached Paracress bug image and a disposable colocated repository containing
its proxy-commands.json and empty .agent-git-bug directory. Never use a work repo.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import runpy
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from lima.proxy_forward import control, local_path
from lima.proxy_socket import directory


def frame(value):
    body = json.dumps(value).encode()
    return struct.pack('>I', len(body)) + body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    repo = args.repo.resolve(strict=True)
    router = runpy.run_path(str(ROOT / 'sandbox-proxies.py'))
    image = runtime.inspect_image(args.image).reference
    prefix = 'forward-test-long-socket-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='forward-test-') as temporary:
        work = Path(temporary)
        os.environ['XDG_RUNTIME_DIR'] = temporary
        images, state = work / 'images.json', work / 'state.json'
        images.write_text(json.dumps({'bug': image}))
        manifest = repo / '.agents/sandbox/proxy-commands.json'
        common = ['--repo', str(repo), '--container-repo', '/src/work',
                  '--state', str(state), '--manifest', str(manifest)]
        try:
            assert router['main'](['start', *common, '--prefix', prefix, '--helper-image', image,
                                   '--network', 'none', '--images', str(images)], runtime=runtime) == 0
            saved = json.loads(state.read_text())
            proxy, = saved['proxies']
            owner = proxy['forwarding']['owner']
            assert len(os.fsencode(proxy['forwarding']['target'])) >= 108, 'exercise long guest path'
            container = runtime.inspect_container(proxy['container'])
            assert container['HostConfig']['NetworkMode'] == 'none'
            assert container['Config']['WorkingDir'] == '/src/work'
            assert container['Config']['Entrypoint'] == ['bb-bug-proxy']
            mounts = {m['Destination']: m['RW'] for m in container['Mounts']}
            assert not mounts['/src/work'] and mounts['/src/work/.agent-git-bug']
            assert router['main'](['publish', *common], runtime=runtime) == 0
            session = router['runtime_directory'](repo)
            metadata = json.loads((session / 'session.json').read_text())
            cache_args = argparse.Namespace(container_repo='/src/work', helper_image=image)
            parsed = router['load_manifest_file'](manifest)
            assert router['cached_session_state'](cache_args, repo, metadata, parsed) is not None
            old = json.loads(json.dumps(metadata))
            del old['state']['proxies'][0]['forwarding']
            assert router['cached_session_state'](cache_args, repo, old, parsed) is None
            incomplete = json.loads(json.dumps(metadata))
            del incomplete['state']['proxies'][0]['volume-owner']
            assert router['cached_session_state'](cache_args, repo, incomplete, parsed) is None
            agent_args = work / 'agent-args'
            assert router['main'](['agent-args', *common, '--output', str(agent_args)], runtime=runtime) == 0
            assert 'dst=/src/work/.agent-git-bug,readonly' in agent_args.read_text()
            route = [sys.executable, str(ROOT / 'sandbox-proxies.py'), 'route',
                     '--repo', str(repo), '--command', 'bug', '--', '/usr/bin/false']
            with (session / 'session.lock').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                request = frame({'version': 1, 'command': 'bug', 'argv': ['list'], 'stdin': ''})
                def routed(data):
                    return subprocess.run(route, input=data, capture_output=True, timeout=15, check=True).stdout
                for data in (request, frame({'malformed': True}), request + b'trailing'):
                    expected = runtime.run(['exec', '-i', proxy['container'],
                        '/trusted/bin/sandbox-proxy-forward'], input=data, capture_output=True, text=False,
                        check=False).stdout
                    actual = routed(data)
                    assert actual == expected, (actual, expected)
                    if data == request:
                        size, = struct.unpack('>I', actual[:4])
                        assert len(actual) == size + 4
                for signum in (signal.SIGTERM, signal.SIGKILL):
                    ready = work / ('sent-' + str(signum))
                    observed = [sys.executable, str(ROOT / 'tests/proxy_route_fixture.py'), str(ready), *route[2:]]
                    child = subprocess.Popen(observed, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE)
                    try:
                        child.stdin.write(request[:8])
                        child.stdin.flush()
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            if ready.exists():
                                break
                            assert child.poll() is None
                            time.sleep(.05)
                        else:
                            raise AssertionError('router never sent its request')
                        child.send_signal(signum)
                        child.stdin.close()
                        child.stdin = None
                        child.communicate(timeout=5)
                        assert child.returncode == (143 if signum == signal.SIGTERM else -9)
                        started = time.monotonic()
                        assert routed(request)
                        assert time.monotonic() - started < 4, 'cancelled request retained server connection'
                    finally:
                        if child.poll() is None:
                            child.kill()
                            child.communicate(timeout=5)
            # Model a master that forgot this registration, leaving a stale inode.
            assert control(runtime, owner, 'cancel').returncode == 0
            local_path(owner).unlink(missing_ok=True)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
                stale.bind(str(local_path(owner)))
            assert router['cached_session_state'](cache_args, repo, metadata, parsed) is None
            print('PASS: manifest policy, framed responses, TERM/KILL cancellation, long socket path')
        finally:
            if state.exists():
                assert router['main'](['stop', '--state', str(state)], runtime=runtime) == 0
                assert router['main'](['stop', '--state', str(state)], runtime=runtime) == 0
                for proxy in json.loads(state.read_text())['proxies']:
                    assert not directory(proxy['forwarding']['owner']).exists()
        print('PASS: stale listener recovery and repeated cleanup')


if __name__ == '__main__':
    main()
