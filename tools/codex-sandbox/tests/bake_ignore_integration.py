"""Compare bundled Bake resolution with BuildKit on disposable ignore fixtures."""

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bake
from sandbox_runtime import image_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True, help='existing Lima-Docker host state')
    args = parser.parse_args()
    runtime = image_runtime('lima-docker', args.state)
    cases = [
        ('case', 'README.md\n', None, ['README.md', 'readme.md'], {'readme.md'}),
        ('wildcard', '**\n!**/a.txt\n', None,
         ['foo/a.txt', 'foo/bar/a.txt', 'target/a.txt'],
         {'foo/a.txt', 'foo/bar/a.txt', 'target/a.txt'}),
        ('ancestor', '**/cache\n!cache/keep.txt\n', None,
         ['cache/drop.txt', 'cache/keep.txt', 'src/cache/drop.txt'], {'cache/keep.txt'}),
        ('specific', 'keep\n', 'drop\n', ['keep', 'drop'], {'keep'}),
    ]
    with tempfile.TemporaryDirectory(prefix='bake-ignore-integration-') as temporary:
        directory = Path(temporary)
        for name, rules, specific, files, expected in cases:
            root = directory / name
            root.mkdir()
            (root / 'Dockerfile').write_text('FROM scratch\nCOPY . /\n')
            (root / '.dockerignore').write_text(rules)
            if specific is not None:
                (root / 'Dockerfile.dockerignore').write_text(specific)
            for relative in files:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative)
            output = directory / (name + '-control')
            subprocess.run(runtime.argv([
                'buildx', 'build', '--builder', 'default', '--progress=plain',
                '--provenance=false', '--output', f'type=local,dest={output}', str(root),
            ]), check=True, timeout=60)
            control = {path.relative_to(output).as_posix(): path.read_bytes()
                       for path in output.rglob('*') if path.is_file()}
            assert set(control) & set(files) == expected, (name, control)
            # A unique label limits cleanup to images owned by this probe.
            declaration = {'target': {'base': {
                'context': '.', 'dockerfile': 'Dockerfile',
                'labels': {'dev.codex.ignore-probe': uuid.uuid4().hex},
            }}}
            image = None
            container = None
            try:
                image = bake.resolve(runtime, root, ['base'], declaration=declaration)['base']
                container = subprocess.run(runtime.argv([
                    'create', '--entrypoint', '/unused', image,
                ]), check=True, capture_output=True, text=True, timeout=30).stdout.strip()
                exported = subprocess.run(runtime.argv(['export', container]),
                                          check=True, capture_output=True, timeout=30).stdout
                # Docker adds these container files after building the image.
                generated = {'.dockerenv', 'dev/console', 'etc/hosts',
                             'etc/hostname', 'etc/resolv.conf'}
                with tarfile.open(fileobj=io.BytesIO(exported)) as archive:
                    actual = {member.name: archive.extractfile(member).read()
                              for member in archive.getmembers() if member.isfile()
                              and member.name not in generated}
                assert actual == control, (name, actual, control)
                # An ignored file edit must select exactly the same accepted image.
                excluded = set(files) - expected
                if excluded:
                    (root / sorted(excluded)[0]).write_text('changed ignored contents')
                    assert bake.resolve(runtime, root, ['base'], declaration=declaration)['base'] == image
                print(json.dumps({'case': name, 'payload': sorted(expected),
                                  'captured_image_matches_buildkit': True}), flush=True)
            finally:
                if container is not None:
                    subprocess.run(runtime.argv(['rm', container]), check=True, timeout=30)
                if image is not None:
                    subprocess.run(runtime.argv(['image', 'rm', image.split('@')[0]]),
                                   check=True, timeout=30)


if __name__ == '__main__':
    main()
