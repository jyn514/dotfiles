"""Run final volume maintenance using the admitted Docker runtime and agent image.

Only owned scratch repositories, containers, and volumes are mutated.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))
from docker_runtime import Docker
from workspace_layout import discover_workspace, ensure_request_lock, workspace_work_volume
from work_storage import cleanup_work_storage
from sandbox_runtime import runtime_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    image = runtime.inspect_image(args.image)
    spec = importlib.util.spec_from_file_location('cleanup_integration_proxies', DIRECTORY / 'sandbox-proxies.py')
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    jj = os.environ.get('DOTFILES_TEST_JJ_REAL', 'jj')
    with tempfile.TemporaryDirectory(prefix='work-cleanup-', dir=runtime.host.state / 'scratch') as directory:
        root = Path(directory)
        repo = root / 'repo'
        subprocess.run([jj, 'git', 'init', '--colocate', str(repo)], check=True)
        (repo / 'work').mkdir()
        layout = discover_workspace(repo, Path('/home/codex/src/fixture'), root)
        ensure_request_lock(layout)
        volume, owner = workspace_work_volume(layout)
        runtime.create_owned_volume(volume, os.getuid(), os.getgid(), owner, role='workspace-work')
        try:
            protected = root / 'protected'
            protected.mkdir()
            (protected / 'keep.tmp').write_text('nested bind canary')
            nested_mount = False
            def mounts(staging):
                arguments = helpers.shared_workspace_mount_args([layout.to_dict()], staging, runtime=runtime)
                if nested_mount:
                    arguments += ['--mount', f'type=bind,src={protected},dst={layout.guest_root}/work/child/cache/mounted']
                return arguments
            for mode in ('seed', 'check'):
                if mode == 'check':
                    # Exercise actual nested mounts in the maintenance process,
                    # then verify the session entrypoint can repeat maintenance.
                    cleanup_work_storage(runtime, [layout], image.reference, mounts, runtime.host.state / 'scratch')
                    helpers.cleanup_session_work_storage(
                        {'version': 4, 'accepted': {'images': {'agent': image.reference}}},
                        {'runtime': runtime_identity(runtime),
                         'proxies': [{'name': 'jj', 'workspaces': [layout.to_dict()]}]})
                staging = root / ('mounts-' + mode)
                staging.mkdir()
                (staging / 'tmp').mkdir()
                probe = Path(__file__).with_name('work_cleanup_probe.py')
                options = ['--network', 'none', '--user', f'{os.getuid()}:{os.getgid()}',
                           '--cap-drop=ALL', '--read-only', '--mount', f'type=bind,src={staging / "tmp"},dst=/tmp',
                           '--env', 'XDG_CONFIG_HOME=/tmp/config', '--env', 'XDG_CACHE_HOME=/tmp/cache',
                           '--entrypoint', 'python3', '--workdir', str(layout.guest_root),
                           '--mount', f'type=bind,src={probe},dst=/probe.py,readonly', *mounts(staging)]
                with runtime.workload(image, 'work-cleanup-fixture-' + uuid.uuid4().hex[:12],
                                      options, ['/probe.py', mode]) as process:
                    assert process.wait() == 0
                if mode == 'seed':
                    nested_mount = True
                    # Old launchers contribute real mounts without new locks.
                    holder = 'work-cleanup-holder-' + uuid.uuid4().hex[:12]
                    with runtime.workload(image, holder, options, ['/probe.py', 'hold']):
                        cleanup_work_storage(runtime, [layout], image.reference, mounts, runtime.host.state / 'scratch')
                        runtime.run(['exec', holder, 'python3', '/probe.py', 'busy'])
            assert (protected / 'keep.tmp').read_text() == 'nested bind canary'
            print('PASS: final volume cleanup preserves snapshotted JJ work and deletes ignored output')
        finally:
            runtime.run(['volume', 'rm', volume], stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr)
        raise
