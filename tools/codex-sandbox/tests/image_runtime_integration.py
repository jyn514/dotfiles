from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "tools" / "codex-sandbox" / "image" / "Dockerfile"
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


def build(tag: str, pi_revision: str, base_image: str | None = None, *,
          jj_image: str, cache_tag: str) -> None:
    command = [
        "docker", "build", "-f", str(DOCKERFILE),
        "--build-arg", f"PI_REVISION={pi_revision}",
        "--build-arg", f"JJ_IMAGE={jj_image}",
    ]
    if base_image is not None:
        command.extend(["--build-arg", f"BASE_IMAGE={base_image}"])
    command.extend(["-t", tag, "-t", cache_tag, "."])
    subprocess.run(command, cwd=ROOT, check=True)


def check_guest(tag: str, revision: str, node_prefix: str, jj_checksum: str) -> None:
    label = run(
        'docker', 'image', 'inspect', '--format',
        '{{ index .Config.Labels "dev.codex.pi-revision" }}', tag,
    ).strip()
    if label != revision:
        raise RuntimeError(f'unexpected Pi revision label: {label!r}')
    output = run(
        'docker', 'run', '--rm', '--interactive', '--entrypoint', 'sh', tag,
        '-c', RUNTIME_PROBE.read_text(), input=WRAPPED_COMMAND_PROBE.read_text(),
    ).splitlines()
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
        subprocess.run([
            'docker', 'build', '-f', 'tools/jj-proxy/Dockerfile',
            *[argument for name, value in jj_release_args().items()
              for argument in ('--build-arg', f'{name}={value}')],
            '-t', jj_image, '-t', jj_cache, '.',
        ], cwd=ROOT, check=True)
        colocated = run(
            'docker', 'run', '--rm', '--interactive', '--tmpfs', '/tmp:mode=1777',
            '--entrypoint', '/trusted/bin/sh', jj_image,
            input=Path(__file__).with_name('fixtures').joinpath('jj-colocated.sh').read_text(),
        )
        checksum, _, workspace = colocated.partition('\n')
        if not workspace.endswith('jj-colocated-ok\n') or not checksum.split():
            raise RuntimeError(f'unexpected colocated JJ workspace probe: {colocated!r}')
        jj_checksum = checksum.split()[0]
        for tag, cache_tag, base_image in (
            (alpine, alpine_cache, None),
            (debian, debian_cache, "node:20-bookworm-slim"),
        ):
            build(tag, args.expected_revision, base_image, jj_image=jj_image, cache_tag=cache_tag)
            expected_node = 'v24.' if tag == alpine else 'v20.'
            check_guest(tag, args.expected_revision, expected_node, jj_checksum)
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
