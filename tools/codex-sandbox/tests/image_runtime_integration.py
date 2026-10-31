from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile
from unittest import mock
import uuid


ROOT = Path(__file__).resolve().parents[3]
WRAPPED_COMMAND_PROBE = Path(__file__).with_name("wrapped_command_probe.clj")
RUNTIME_PROBE = Path(__file__).with_name('fixtures') / 'image-runtime.sh'
IMAGE_PREFIX = 'codex-sandbox'
sys.path.insert(0, str(ROOT / 'tools/codex-sandbox'))
from owned_images import jj_release_args
from shared_workspace_probe import probe_shared_workspaces


def run(*args: str, input: str | bytes | None = None) -> str:
    output = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=not isinstance(input, bytes),
        input=input,
    ).stdout
    return output.decode() if isinstance(output, bytes) else output


def build_images(pi_revision: str | None, tags: dict[str, tuple[str, str]]) -> None:
    platform = run('docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}').strip()
    targets = {
        'jj': {'context': '.', 'dockerfile': 'tools/jj-proxy/Dockerfile',
               'args': jj_release_args(platform), 'tags': list(tags['jj']), 'platforms': [platform]},
    }
    for variant, base in (('pi-alpine', None), ('pi-debian', 'node:20-bookworm-slim')):
        if variant not in tags:
            continue
        arguments = {'PI_REVISION': pi_revision, 'JJ_IMAGE': 'jj-artifact'}
        if base is not None:
            arguments['BASE_IMAGE'] = base
        targets[variant] = {
            'context': '.', 'dockerfile': 'tools/codex-sandbox/image/Dockerfile',
            'args': arguments, 'tags': list(tags[variant]),
            'platforms': [platform],
            # Consume the same JJ build result without a tag-resolution round trip.
            'contexts': {'jj-artifact': 'target:jj'},
        }
    definition = {'group': {'default': {'targets': list(targets)}}, 'target': targets}
    with tempfile.TemporaryDirectory(prefix='sandbox-runtime-bake-') as directory:
        path = Path(directory) / 'docker-bake.json'
        path.write_text(json.dumps(definition))
        # Probes need engine-local images even with a docker-container builder.
        subprocess.run(['docker', 'buildx', 'bake', '--file', str(path), '--load'], cwd=ROOT, check=True)


def probe_jj_mounts(image: str) -> None:
    from docker_runtime import Docker
    from workspace_layout import discover_workspace, ensure_request_lock

    launcher = runpy.run_path(str(ROOT / 'tools/codex-sandbox/sandbox-proxies.py'))
    generate = launcher['proxy_repository_mount_args']
    container_repo = Path('/src/work')
    with tempfile.TemporaryDirectory(prefix='jj-mount-fixture-') as directory:
        root = Path(directory).resolve()
        repo = root / 'repo'
        jj = os.environ.get('DOTFILES_TEST_JJ_REAL', 'jj')
        subprocess.run([jj, 'git', 'init', '--colocate', str(repo)], cwd=root, check=True)

        def native(arguments, *, capture, cwd=None):
            if arguments[0] == 'jj':
                arguments = [jj, *arguments[1:]]
            return subprocess.run(arguments, cwd=cwd, check=True, text=True, capture_output=capture)

        layout = discover_workspace(repo, container_repo, root, runner=native)
        ensure_request_lock(layout)
        records = [layout.to_dict()]
        staging = root / 'proxy-staging'
        staging.mkdir()
        sandbox = repo / '.agents/sandbox'
        sandbox.mkdir(parents=True)
        (sandbox / 'Dockerfile').write_text('FROM scratch\n')
        command = {'mounts': [{'source': '.', 'target': '.', 'proxy': 'read-write'}]}
        # Select the production Docker mount grammar without requiring host startup state.
        with mock.patch.object(generate.__globals__['OUTER_RUNTIME'], 'nonrecursive_bind', Docker.nonrecursive_bind), \
                mock.patch.dict(os.environ, {'HOME': str(root)}):
            mounts = generate(repo, container_repo, 'jj', command, workspaces=records, staging=staging)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            # Every generated bind source, including locks and source-view scaffolding,
            # must survive relocation into the daemon's private fixture volume.
            for path in root.iterdir():
                tar.add(path, arcname=path.name)
        name = 'jj-mount-fixture-' + uuid.uuid4().hex
        created = False
        try:
            run('docker', 'volume', 'create', name)
            created = True
            daemon_root = Path(run('docker', 'volume', 'inspect', '--format', '{{.Mountpoint}}', name).strip())
            user = run('docker', 'image', 'inspect', '--format', '{{.Config.User}}', image).strip() or '0:0'
            seed = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--user', '0:0',
                    '--mount', f'type=volume,src={name},dst=/fixture',
                    '--entrypoint', '/trusted/bin/busybox']
            subprocess.run([*seed, '--interactive', image, 'tar', 'xf', '-', '-C', '/fixture'],
                           input=archive.getvalue(), check=True)
            run(*seed, image, 'chown', '-R', user, '/fixture')
            # The daemon cannot see our temporary directory. Relocate only bind
            # sources to its populated volume; retain every destination and mode.
            relocated = []
            for argument in mounts:
                fields = argument.split(',')
                for index, field in enumerate(fields):
                    if field.startswith('src='):
                        relative = Path(field.removeprefix('src=')).relative_to(root)
                        fields[index] = 'src=' + str(daemon_root / relative)
                relocated.append(','.join(fields))
            output = run(
                'docker', 'run', '--rm', '--interactive', '--name', name, '--network', 'none',
                '--cap-drop=ALL', '--read-only', '--tmpfs', '/tmp:mode=1777',
                '--tmpfs', '/run/sandbox-proxy:mode=1777', *relocated,
                '--env', 'JJ_PROXY_REPO=' + str(container_repo),
                '--env', 'JJ_PROXY_WORKSPACES=' + launcher['workspace_environment'](records),
                '--workdir', str(container_repo), '--entrypoint', '/trusted/bin/sh', image,
                input=Path(__file__).with_name('fixtures').joinpath('jj-mounted-checkout.sh').read_text(),
            )
            if output != 'jj-mounted-checkout-ok\n':
                raise RuntimeError(f'unexpected mounted JJ checkout probe: {output!r}')
        finally:
            subprocess.run(['docker', 'rm', '-f', name], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if created:
                run('docker', 'volume', 'rm', name)


def check_labels(tags: list[str], revision: str) -> None:
    labels = run(
        'docker', 'image', 'inspect', '--format',
        '{{ index .Config.Labels "dev.codex.pi-revision" }}', *tags,
    ).splitlines()
    if labels != [revision] * len(tags):
        raise RuntimeError(f'unexpected Pi revision labels: {labels!r}')


def probe_guest(tag: str) -> list[str]:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        for path in (WRAPPED_COMMAND_PROBE,
                     RUNTIME_PROBE.with_name('pi-runtime-package.mjs'),
                     RUNTIME_PROBE.with_name('pi-runtime-worker.mjs'),
                     RUNTIME_PROBE.with_name('node-cache.py')):
            tar.add(path, arcname=path.name)
    return run(
        'docker', 'run', '--rm', '--interactive', '--entrypoint', 'sh', tag,
        '-c', RUNTIME_PROBE.read_text(), input=archive.getvalue(),
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
    parser = argparse.ArgumentParser(description='Build and check the JJ proxy and Pi runtime images.')
    parser.add_argument('--jj-only', action='store_true', help='build and probe only the JJ proxy image')
    parser.add_argument('--expected-revision', help='expected Pi commit in the built images; required unless --jj-only')
    args = parser.parse_args()
    if not args.jj_only and not args.expected_revision:
        parser.error('--expected-revision is required unless --jj-only is selected')
    suffix = uuid.uuid4().hex

    def image_tags(variant: str) -> tuple[str, str]:
        repository = f'{IMAGE_PREFIX}-{variant}-test'
        # Checks use the per-run alias; only the shared cache alias outlives cleanup.
        return f'{repository}:{suffix}', f'{repository}:cache'

    tags = {'jj': image_tags('jj')}
    if not args.jj_only:
        tags.update({variant: image_tags(variant) for variant in ('pi-alpine', 'pi-debian')})
    jj_image = tags['jj'][0]
    try:
        build_images(args.expected_revision, tags)
        probe_jj_mounts(jj_image)
        probe_shared_workspaces(jj_image)
        probe_shared_workspaces(jj_image, linked=True)
        if not args.jj_only:
            check_labels([tags['pi-alpine'][0], tags['pi-debian'][0]], args.expected_revision)
        # Leaving the executor waits for every probe, including on failure,
        # before the outer finally can remove their image aliases.
        with ThreadPoolExecutor(max_workers=len(tags)) as probes:
            colocated = probes.submit(
                run, 'docker', 'run', '--rm', '--interactive', '--network', 'none',
                '--tmpfs', '/tmp:mode=1777', '--tmpfs', '/run/sandbox-proxy:mode=1777',
                '--tmpfs', '/src:mode=1777', '--tmpfs', '/run/jj-locks:mode=1777',
                '--entrypoint', '/trusted/bin/sh', jj_image,
                input=Path(__file__).with_name('fixtures').joinpath('jj-colocated.sh').read_text(),
            )
            guests = [(probes.submit(probe_guest, tags[variant][0]), expected_node)
                      for variant, expected_node in (('pi-alpine', 'v24.'), ('pi-debian', 'v20.'))
                      if variant in tags]
            output = colocated.result()
            checksum, _, workspace = output.partition('\n')
            if not workspace.endswith('jj-colocated-ok\n') or not checksum.split():
                raise RuntimeError(f'unexpected colocated JJ workspace probe: {output!r}')
            jj_checksum = checksum.split()[0]
            for guest, expected_node in guests:
                check_guest(guest.result(), args.expected_revision, expected_node, jj_checksum)
    finally:
        subprocess.run(
            ["docker", "image", "rm", "-f", *[aliases[0] for aliases in tags.values()]],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    remaining = set(run(
        'docker', 'image', 'ls', '--filter', f'reference={IMAGE_PREFIX}-*-test:*',
        '--format', '{{.Repository}}:{{.Tag}}',
    ).splitlines())
    missing = {aliases[1] for aliases in tags.values()} - remaining
    if missing:
        raise RuntimeError(f'cleanup lost runtime image caches: {sorted(missing)}')
    leaked = {aliases[0] for aliases in tags.values()} & remaining
    if leaked:
        raise RuntimeError(f'cleanup left per-run image aliases: {sorted(leaked)}')


if __name__ == "__main__":
    main()
