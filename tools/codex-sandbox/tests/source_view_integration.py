"""Reproduce missing worktree mountpoints using owned, networkless containers."""

import argparse
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docker_runtime import Docker
from source_view import source_mounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path.home() / '.local/state/codex-sandbox-docker')
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    runtime = Docker(args.state)
    image = runtime.inspect_image(args.image)
    with tempfile.TemporaryDirectory(prefix='source-view-', dir=runtime.host.state / 'scratch') as directory:
        root = Path(directory)
        source, repo, metadata = [root / name for name in ('src', 'worktree', 'metadata')]
        for path in (source / 'team', repo, metadata):
            path.mkdir(parents=True)
        (source / 'team/sibling').write_text('visible')
        (source / 'alias').symlink_to('team/sibling')
        (source / 'repository').mkdir()
        (source / 'repository/old').touch()
        (metadata / 'marker').write_text('protected')
        destinations = [Path('/src/repository'), Path('/src/team/main/.git')]
        overlays = ['--mount', f'type=bind,src={repo},dst={destinations[0]}',
                    '--mount', f'type=bind,src={metadata},dst={destinations[1]},readonly']
        script = Path(__file__).with_name('source_view_probe.py')
        common = ['--network', 'none', '--cap-drop=ALL', '--read-only', '--entrypoint', 'python3',
                  '--mount', f'type=bind,src={script},dst=/probe.py,readonly']
        baseline_name = 'source-view-baseline-' + uuid.uuid4().hex[:12]
        try:
            baseline = runtime.run(['run', '--rm', '--name', baseline_name, *common,
                                    '--mount', f'type=bind,src={source},dst=/src,readonly',
                                    *overlays, image.config, '/probe.py'], check=False, capture_output=True)
        finally:
            runtime.terminate(baseline_name)
        assert baseline.returncode != 0 and 'read-only file system' in baseline.stderr, baseline.stderr
        print('PASS: original parent bind reproduces the read-only mountpoint failure', flush=True)
        name = 'source-view-' + uuid.uuid4().hex[:12]
        with runtime.workload(image, name, [*common, *source_mounts(source, destinations, root / 'view'),
                                           *overlays], ['/probe.py']) as process:
            assert process.wait(timeout=20) == 0
        assert list((source / 'repository').iterdir()) == [source / 'repository/old']
        assert not (source / 'team/main').exists()
        assert (repo / 'created').read_text() == 'writable'
        print('PASS: external worktree writable, source and metadata read-only, no host placeholders', flush=True)


if __name__ == '__main__':
    main()
