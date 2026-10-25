"""Read-only guest ownership checks for the host launcher's Docker admission."""

import json
from pathlib import Path
import subprocess
import sys


def check_virtiofs(scratch, mapping, *, proc=Path('/proc')):
    # Match the previous `stat -c` invocation: inspect the path itself, not
    # a symlink target. Admission must not silently accept different inputs.
    ownership = Path(scratch).lstat()
    actual = (ownership.st_uid, ownership.st_gid)
    expected = (mapping['guest_uid'], mapping['guest_gid'])
    if actual != expected:
        raise ValueError(f'Linux virtiofs UID map is inactive ({actual[0]}:{actual[1]}; '
                         f'expected {expected[0]}:{expected[1]}); restart through docker_host.py')
    pids = subprocess.run(['pgrep', '-x', 'dockerd'], check=True,
                          capture_output=True, text=True).stdout.split()
    if len(pids) != 1 or not pids[0].isdigit():
        raise ValueError('expected exactly one rootless Docker daemon')
    for kind in ('uid', 'gid'):
        lines = (proc / pids[0] / (kind + '_map')).read_text().splitlines()
        pairs = [tuple(map(int, line.split())) for line in lines]
        container_id = mapping['host_' + kind]
        guest_id = mapping['guest_' + kind]
        if not any(start <= container_id < start + length and
                   outer + container_id - start == guest_id
                   for start, outer, length in pairs):
            raise ValueError(f'Docker {kind} namespace does not map agent ID to virtiofs owner')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        check_virtiofs(request['scratch'], request['mapping'])
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
