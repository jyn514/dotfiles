"""Exercise production helper creation using local Docker in the owned guest."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker

spec = importlib.util.spec_from_file_location('sandbox_proxies', ROOT / 'sandbox-proxies.py')
proxies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxies)


class GuestDocker(Docker):
    # Only transport/forwarding differ: creation and volume initialization
    # execute the production paths. No host forwarding is needed inside the VM.
    provider = 'guest-fixture'

    def __init__(self):
        pass

    def argv(self, arguments, **kwargs):
        return ['docker', *arguments]

    def run(self, arguments, **kwargs):
        kwargs.setdefault('check', True)
        kwargs.setdefault('timeout', 30)
        kwargs.setdefault('text', True)
        return subprocess.run(self.argv(arguments), **kwargs)

    def guest(self, arguments, **kwargs):
        kwargs.setdefault('check', True)
        kwargs.setdefault('timeout', 30)
        return subprocess.run(arguments, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    owner = GuestDocker()
    proxies.OUTER_RUNTIME = owner
    args.prefix = 'reclaim-proxy-' + uuid.uuid4().hex[:12]
    args.container_repo = '/src/reclaim'
    args.network = 'none'
    args.state = str(args.repo / 'proxy-state.json')
    credential = args.repo / 'dummy-zuliprc'
    credential.write_text('[api]\nkey=fixture-only\n')
    credential.chmod(0o600)
    args.zuliprc = str(credential)
    state = {'proxies': []}
    name = args.prefix + '-zulip'
    command = {'network': False, 'workdir': '.', 'mounts': [],
               'argv': ['python3', '/src/reclaim/probe.py', 'readwait', '/src/reclaim/helper']}
    try:
        proxies.start_one_proxy(args, args.repo, args.prefix, {'zulip': args.image},
                                state, threading.Lock(), 'zulip', command)
        deadline = time.monotonic() + 15
        while 'ready' not in owner.run(['logs', name], capture_output=True).stdout:
            if time.monotonic() >= deadline:
                raise TimeoutError('proxy corpus read did not finish')
            time.sleep(0.05)
        pid = owner.run(['inspect', '--format', '{{.State.Pid}}', name], capture_output=True).stdout.strip()
        group = Path('/proc', pid, 'cgroup').read_text().strip()
        assert '/sandbox.slice/docker-' in group, group
        (args.repo / 'release').touch()
        result = owner.run(['wait', name], capture_output=True).stdout.strip()
        assert result == '0', result
        print(json.dumps({'helper_cgroup': group}), flush=True)
    finally:
        owner.run(['rm', '-f', name], check=False, capture_output=True)
        owner.run(['volume', 'rm', name], check=False, capture_output=True)
        credential.unlink()


if __name__ == '__main__':
    main()
