"""Recover owned resources after policy damage, including a failed cleanup retry."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from sandbox_runtime import RuntimeError, runtime_identity, verification_scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--disposable-instance', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    assert runtime.record['instance'] == args.disposable_instance != 'sandbox-host-docker'
    assert not runtime.run(['ps', '-q'], capture_output=True).stdout.strip()
    image = runtime.inspect_image(args.image)
    prefix = 'recovery-' + uuid.uuid4().hex[:12]
    container, unrelated, volume, network = [prefix + '-' + name for name in ('agent', 'unrelated', 'volume', 'network')]
    owner = uuid.uuid4().hex
    policy = '/usr/local/share/codex-sandbox/network-policy.json'
    original = runtime.guest(['cat', policy], capture_output=True).stdout
    try:
        runtime.create_relay_network(network, internal=True, owner=owner)
        runtime.run(['volume', 'create', '--label', 'dev.codex.volume-owner=' + owner, volume])
        for name in (container, unrelated):
            runtime.run(['run', '-d', '--name', name, '--network', 'none',
                         '--entrypoint', 'sleep', image.config, '300'])
        runtime.guest(['sudo', 'tee', policy], input=b'{}', stdout=subprocess.DEVNULL)
        with verification_scope():
            admitted = Docker(args.state)
            try:
                admitted.host.doctor(admitted.record)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('doctor accepted damaged policy')
        recovery = Docker(args.state, recovery=True)
        for command in (['run', image.config], ['exec', unrelated, 'true'], ['network', 'create', 'forbidden']):
            try:
                recovery.argv(command)
            except RuntimeError:
                pass
            else:
                raise AssertionError('recovery authorized workload execution')
        recovery.record = {**recovery.record, 'engine_id': 'replacement'}
        try:
            recovery.terminate(container)
        except RuntimeError:
            pass
        else:
            raise AssertionError('wrong engine identity authorized deletion')
        assert runtime.run(['inspect', '--format', '{{.State.Running}}', container], capture_output=True).stdout.strip() == 'true'
        with tempfile.TemporaryDirectory(dir=runtime.host.state / 'scratch') as directory:
            record = Path(directory) / 'session.json'
            state = {'runtime': runtime_identity(runtime), 'proxies': [
                {'container': container, 'volume': volume, 'volume-owner': 'wrong-owner'}]}
            record.write_text(json.dumps(state))
            command = [sys.executable, str(ROOT / 'sandbox-proxies.py'), 'stop', '--state', str(record)]
            environment = {**os.environ, 'CODEX_SANDBOX_RUNTIME': 'podman'}
            environment.pop('CODEX_SANDBOX_LIMA_VERIFIED', None)
            failed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
            assert failed.returncode == 1 and 'another creator' in failed.stderr, failed.stderr
            assert runtime.run(['inspect', container], check=False, capture_output=True).returncode != 0
            assert record.exists() and runtime.run(['volume', 'inspect', volume], check=False, capture_output=True).returncode == 0
            state['proxies'][0]['volume-owner'] = owner
            record.write_text(json.dumps(state))
            subprocess.run(command, env=environment, check=True, timeout=60)
        recovery = Docker(args.state, recovery=True)
        recovery.run(['network', 'rm', network])
        assert recovery.run(['volume', 'inspect', volume], check=False, capture_output=True).returncode != 0
        assert recovery.run(['inspect', '--format', '{{.State.Running}}', unrelated], capture_output=True).stdout.strip() == 'true'
        print('PASS: damaged-policy recovery, wrong-engine refusal, partial-cleanup retry, unrelated workload preserved', flush=True)
    finally:
        runtime.guest(['sudo', 'tee', policy], input=original, stdout=subprocess.DEVNULL)
        for name in (container, unrelated):
            runtime.run(['rm', '-f', name], check=False, capture_output=True)
        runtime.run(['volume', 'rm', volume], check=False, capture_output=True)
        runtime.run(['network', 'rm', network], check=False, capture_output=True)
        with verification_scope():
            runtime.host.doctor(runtime.record)


if __name__ == '__main__':
    main()
