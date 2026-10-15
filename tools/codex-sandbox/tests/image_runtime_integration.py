from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[3]
WRAPPED_COMMAND_PROBE = Path(__file__).with_name("wrapped_command_probe.clj")
RUNTIME_PROBE = Path(__file__).with_name('fixtures') / 'image-runtime.sh'
IMAGE_PREFIX = 'codex-sandbox'
sys.path.insert(0, str(ROOT / 'tools/codex-sandbox'))
from owned_images import jj_release_args


def run(*args: str, input: str | None = None) -> str:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        input=input,
    ).stdout


def build_images(pi_revision: str, tags: dict[str, tuple[str, str]]) -> None:
    targets = {
        'jj': {'context': '.', 'dockerfile': 'tools/jj-proxy/Dockerfile',
               'args': jj_release_args(), 'tags': list(tags['jj'])},
    }
    for variant, base in (('pi-alpine', None), ('pi-debian', 'node:20-bookworm-slim')):
        arguments = {'PI_REVISION': pi_revision, 'JJ_IMAGE': 'jj-artifact'}
        if base is not None:
            arguments['BASE_IMAGE'] = base
        targets[variant] = {
            'context': '.', 'dockerfile': 'tools/codex-sandbox/image/Dockerfile',
            'args': arguments, 'tags': list(tags[variant]),
            # Consume the same JJ build result without a tag-resolution round trip.
            'contexts': {'jj-artifact': 'target:jj'},
        }
    definition = {'group': {'default': {'targets': list(targets)}}, 'target': targets}
    with tempfile.TemporaryDirectory(prefix='sandbox-runtime-bake-') as directory:
        path = Path(directory) / 'docker-bake.json'
        path.write_text(json.dumps(definition))
        # Probes need engine-local images even with a docker-container builder.
        subprocess.run(['docker', 'buildx', 'bake', '--file', str(path), '--load'], cwd=ROOT, check=True)


def check_labels(tags: list[str], revision: str) -> None:
    labels = run(
        'docker', 'image', 'inspect', '--format',
        '{{ index .Config.Labels "dev.codex.pi-revision" }}', *tags,
    ).splitlines()
    if labels != [revision] * len(tags):
        raise RuntimeError(f'unexpected Pi revision labels: {labels!r}')


def probe_guest(tag: str) -> list[str]:
    return run(
        'docker', 'run', '--rm', '--interactive', '--entrypoint', 'sh', tag,
        '-c', RUNTIME_PROBE.read_text(), input=WRAPPED_COMMAND_PROBE.read_text(),
    ).splitlines()


def check_guest(output: list[str], revision: str, node_prefix: str, jj_checksum: str) -> None:
    if len(output) != 7:
        raise RuntimeError(f'unexpected combined guest probe: {output!r}')
    checksum = output[0].split()
    if not checksum or checksum[0] != jj_checksum:
        raise RuntimeError('guest JJ differs from the proxy binary')
    if (
        not output[1].startswith(node_prefix)
        or output[2] != revision
        or output[4:6] != ['1.3.14', 'bun-test-ok']
    ):
        raise RuntimeError(f'unexpected Pi runtime: {output[1:6]!r}')
    if output[6] != 'wrapped-command-probe-ok':
        raise RuntimeError(f'unexpected wrapped-command probe: {output[6]!r}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Build and check Alpine Node and Debian Bun runtimes.')
    parser.add_argument('--expected-revision', required=True, help='expected Pi commit in the built images')
    args = parser.parse_args()
    suffix = uuid.uuid4().hex

    def image_tags(variant: str) -> tuple[str, str]:
        repository = f'{IMAGE_PREFIX}-{variant}-test'
        # Checks use the per-run alias; only the shared cache alias outlives cleanup.
        return f'{repository}:{suffix}', f'{repository}:cache'

    alpine, alpine_cache = image_tags('pi-alpine')
    debian, debian_cache = image_tags('pi-debian')
    jj_image, jj_cache = image_tags('jj')
    try:
        build_images(args.expected_revision, {
            'jj': (jj_image, jj_cache),
            'pi-alpine': (alpine, alpine_cache),
            'pi-debian': (debian, debian_cache),
        })
        check_labels([alpine, debian], args.expected_revision)
        # Leaving the executor waits for every probe, including on failure,
        # before the outer finally can remove their image aliases.
        with ThreadPoolExecutor(max_workers=3) as probes:
            colocated = probes.submit(
                run, 'docker', 'run', '--rm', '--interactive', '--tmpfs', '/tmp:mode=1777',
                '--entrypoint', '/trusted/bin/sh', jj_image,
                input=Path(__file__).with_name('fixtures').joinpath('jj-colocated.sh').read_text(),
            )
            guests = [(probes.submit(probe_guest, tag), expected_node)
                      for tag, expected_node in ((alpine, 'v24.'), (debian, 'v20.'))]
            output = colocated.result()
            checksum, _, workspace = output.partition('\n')
            if not workspace.endswith('jj-colocated-ok\n') or not checksum.split():
                raise RuntimeError(f'unexpected colocated JJ workspace probe: {output!r}')
            jj_checksum = checksum.split()[0]
            for guest, expected_node in guests:
                check_guest(guest.result(), args.expected_revision, expected_node, jj_checksum)
    finally:
        subprocess.run(
            ["docker", "image", "rm", "-f", alpine, debian, jj_image],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    remaining = set(run(
        'docker', 'image', 'ls', '--filter', f'reference={IMAGE_PREFIX}-*-test:*',
        '--format', '{{.Repository}}:{{.Tag}}',
    ).splitlines())
    missing = {alpine_cache, debian_cache, jj_cache} - remaining
    if missing:
        raise RuntimeError(f'cleanup lost runtime image caches: {sorted(missing)}')
    leaked = {alpine, debian, jj_image} & remaining
    if leaked:
        raise RuntimeError(f'cleanup left per-run image aliases: {sorted(leaked)}')


if __name__ == "__main__":
    main()
