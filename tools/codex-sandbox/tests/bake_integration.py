"""Build only owned tiny images; never restart a VM or touch live containers."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker
from sandbox_build import prepare_launch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    prefix = 'sandbox-bake-test-' + uuid.uuid4().hex
    tags = set()
    with tempfile.TemporaryDirectory(prefix='bake-fixture-') as directory:
        root = Path(directory)
        for role, source in (('base', 'base'), ('auth', 'proxy'), ('proxy', 'proxy')):
            shutil.copyfile(ROOT / f'tests/fixtures/bake-{source}.Dockerfile', root / f'{role}.Dockerfile')
        agent_file = root / 'tools/codex-sandbox/image/Dockerfile'
        agent_file.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tests/fixtures/bake-agent.Dockerfile', agent_file)
        definition = root / '.agents/sandbox/docker-bake.hcl'
        definition.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tests/fixtures/docker-bake.hcl', definition)
        auth = root / 'tools/codex-sandbox/auth-proxy/Dockerfile'
        auth.parent.mkdir(parents=True)
        shutil.copyfile(root / 'auth.Dockerfile', auth)
        (root / 'marker').write_text(prefix)
        (root / 'base-marker').write_text(prefix)
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({'commands': {'probe': {'image-target': 'proxy'}}}))
        state = SimpleNamespace(repository=root, manifest=manifest, uid=os.getuid(), gid=os.getgid(), term='xterm')
        original_bake = runtime.bake
        def owned_bake(targets, **kwargs):
            tags.update(tag for target in targets.values() for tag in target['tags'])
            return original_bake(targets, **kwargs)
        try:
            with patch.object(runtime, 'bake', side_effect=owned_bake) as bake:
                first = prepare_launch(runtime, state, root)
                assert bake.call_count == 1
                targets = bake.call_args.args[0]
                assert set(targets) == {'repo-base', 'trusted-agent', 'trusted-auth', 'repo-proxy'}
                assert targets['trusted-agent']['contexts'] == {'sandbox-base': 'target:repo-base'}
                second = prepare_launch(runtime, state, root)
                assert bake.call_count == 2
                assert first == second, 'cold publication and warm cache identity differ'
                (root / 'base-marker').write_text(prefix + '-changed')
                third = prepare_launch(runtime, state, root)
                assert third[0] != second[0], 'changed base input reused a stale agent image'
                assert third[1] == second[1], 'independent auth image changed'
                assert third[2] != second[2], 'changed base input reused a stale proxy image'
                print('PASS: one Bake per launch; warm identities agree; changed inputs invalidate cache', flush=True)
        finally:
            for tag in set(tags):
                runtime.run(['image', 'rm', tag], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
