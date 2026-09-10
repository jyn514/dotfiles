"""Exercise existing build-if-missing contracts against tiny owned Docker images."""

import argparse
import hashlib
from pathlib import Path
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
    environment = {**runtime.builder_environment(), 'DOCKER_HOST': 'unix:///wrong-engine',
                   'DOCKER_CONTEXT': 'wrong-context'}
    tags = set()
    with tempfile.TemporaryDirectory(prefix='builder-fixture-') as temporary:
        root = Path(temporary)
        (root / 'marker').write_text(uuid.uuid4().hex)
        dockerfile = root / 'Dockerfile'
        dockerfile.write_text('FROM scratch\nCOPY marker /marker\nLABEL revision=one\n')
        def tag():
            value = 'sandbox-builder-test:' + hashlib.sha256(
                dockerfile.read_bytes() + (root / 'marker').read_bytes()).hexdigest()
            tags.add(value)
            return value
        def run(image):
            return subprocess.run(['sh', str(ROOT / 'tests/fixtures/keyed-image.sh'), image],
                                  cwd=root, env=environment, capture_output=True, text=True, timeout=120)
        try:
            first_tag = tag()
            first = run(first_tag)
            assert first.returncode == 0, first.stderr
            assert 'BUILD-MISS' in first.stderr
            reference = runtime.builder_image(first.stdout.strip())
            second = run(first_tag)
            assert second.returncode == 0 and second.stdout == first.stdout, second.stderr
            assert not second.stderr, second.stderr
            dockerfile.write_text(dockerfile.read_text().replace('revision=one', 'revision=two'))
            third = run(tag())
            assert third.returncode == 0 and third.stdout != first.stdout, third.stderr
            assert 'BUILD-MISS' in third.stderr
            assert run(first_tag).stdout == first.stdout
            # The runtime-native helper uses the same tag-existence contract.
            helper = subprocess.run([sys.executable, str(ROOT / 'sandbox-image'), 'build', '--if-missing',
                                     '--tag', first_tag, '--file', str(dockerfile), str(root)],
                                    env=environment, capture_output=True, text=True, timeout=30)
            assert helper.returncode == 0 and helper.stdout.strip() == reference, helper.stderr
            assert not helper.stderr
            # Old repository builders pass the base builder's local config ID.
            # BuildKit must resolve it locally, not pull docker.io/library/sha256.
            dockerfile.write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nLABEL derived=true\n')
            for option in (['--build-arg', 'BASE_IMAGE=' + first.stdout.strip()],
                           ['--build-arg=BASE_IMAGE=' + first.stdout.strip()]):
                derived = subprocess.run(['docker', 'build', '--tag', tag(), *option, '.'],
                                         cwd=root, env=environment, capture_output=True, text=True, timeout=120)
                assert derived.returncode == 0, derived.stderr
                assert 'docker.io/library/sha256:' not in derived.stderr
            dockerfile.write_text('FROM scratch\nCOPY absent /absent\n')
            failed = run(tag())
            assert failed.returncode != 0 and not failed.stdout
            assert 'absent' in failed.stderr and 'Traceback' not in failed.stderr, failed.stderr
            print('PASS: same tag skips build; new tag builds; old tag reuses; failure and engine routing preserved')
        finally:
            for image in tags:
                runtime.run(['image', 'rm', image], check=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
