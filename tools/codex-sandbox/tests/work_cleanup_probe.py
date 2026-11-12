"""Seed/check only the integration runner's disposable guest workspace."""
import os
from pathlib import Path
import subprocess
import sys

root = Path.cwd()
workspace = root / 'work/child'
jj = os.environ['JJ_REAL']

def run(*arguments, cwd=workspace):
    return subprocess.run([jj, *arguments], cwd=cwd, check=True, capture_output=True, text=True).stdout

if sys.argv[1] == 'hold':
    import signal
    signal.pause()
elif sys.argv[1] == 'busy':
    assert (workspace / 'out.tmp').exists()
elif sys.argv[1] == 'seed':
    run('workspace', 'add', '--no-colocate', str(workspace), cwd=root)
    (workspace / '.gitignore').write_text('*.tmp\ncache/\n')
    (workspace / 'keep').write_text('pending work')
    (workspace / 'out.tmp').write_text('ignored output')
    (workspace / 'cache').mkdir()
    (workspace / 'cache/large').write_bytes(b'x' * 1024 * 1024)
    (root / 'work/unclassified').write_text('keep outside registered workspace')
    (root / 'host-canary.tmp').write_text('host-backed canary')
    (workspace / 'escape.tmp').symlink_to(root / 'host-canary.tmp')
else:
    assert not (workspace / 'out.tmp').exists()
    assert not (workspace / 'cache/large').exists()
    assert (workspace / 'keep').read_text() == 'pending work'
    assert run('file', 'show', '--ignore-working-copy', 'keep') == 'pending work'
    assert (workspace / '.jj').is_dir()
    assert (root / 'work/unclassified').exists()
    assert (root / 'host-canary.tmp').read_text() == 'host-backed canary'
    assert not (workspace / 'escape.tmp').is_symlink()
    assert (workspace / 'cache/mounted/keep.tmp').read_text() == 'nested bind canary'
