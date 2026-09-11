"""Exercise fresh Bake metadata and owned local dependency builds in Docker."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docker_runtime import Docker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    builds = []
    tags = set()
    run_builder = runtime.run_builder

    def record(command, **kwargs):
        if '--file' in command and '--print' not in command:
            definition = Path(command[command.index('--file') + 1])
            if definition.name == 'build.json':
                batch = json.loads(definition.read_text())['target']
                builds.append(set(batch))
                tags.update(tag for target in batch.values() for tag in target['tags'])
        return run_builder(command, **kwargs)

    runtime.run_builder = record
    with tempfile.TemporaryDirectory(prefix='bake-fixture-') as temporary:
        root = Path(temporary)
        producer = root / '.agents/sandbox/bake'
        producer.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / 'tests/fixtures/bake-inputs.py', producer)
        producer.chmod(0o755)
        (root / 'base-marker').write_text(uuid.uuid4().hex)
        (root / 'proxy-marker').write_text(uuid.uuid4().hex)
        (root / 'base.Dockerfile').write_text('FROM scratch\nCOPY base-marker /base-marker\n')
        (root / 'proxy.Dockerfile').write_text(
            'ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nCOPY proxy-marker /proxy-marker\n')
        try:
            first = runtime.bake(root, ['base', 'proxy'])
            assert builds == [{'base'}, {'proxy'}], builds
            assert runtime.bake(root, ['base', 'proxy']) == first
            assert len(builds) == 2, 'warm launch invoked a build'
            (root / 'proxy-marker').write_text(uuid.uuid4().hex)
            changed = runtime.bake(root, ['base', 'proxy'])
            assert changed['base'] == first['base'] and changed['proxy'] != first['proxy']
            assert builds[-1] == {'proxy'} and len(builds) == 3
            (root / 'base-marker').write_text(uuid.uuid4().hex)
            rebuilt = runtime.bake(root, ['base', 'proxy'])
            assert rebuilt['base'] != changed['base'] and rebuilt['proxy'] != changed['proxy']
            assert builds[-2:] == [{'base'}, {'proxy'}] and len(builds) == 5
            (root / 'proxy.Dockerfile').write_text('FROM scratch\nCOPY absent /absent\n')
            try:
                runtime.bake(root, ['proxy'])
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('failed build returned an image')
            print('PASS: warm skip, source invalidation, dependency invalidation, local base context, failure')
        finally:
            for tag in tags:
                runtime.run(['image', 'rm', tag], check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
