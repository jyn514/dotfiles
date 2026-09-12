"""Measure cgroup ownership in a caller-owned, idle Docker fixture on macOS.

The fixture must have the candidate Docker default parent installed. This does not
change daemon configuration or touch production VM caches.
"""

import argparse
import ctypes
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from file_pressure import descriptor_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable-instance', required=True)
    parser.add_argument('--work', required=True, type=Path, help='fixture writable host share')
    parser.add_argument('--image', required=True, help='local image with python3')
    parser.add_argument('--vz-pid', type=int, required=True, help='verified fixture VZ process')
    args = parser.parse_args()
    assert args.disposable_instance.startswith('sandbox-host-docker-')
    prefix = ['limactl', 'shell', args.disposable_instance]

    def guest(*argv, **kwargs):
        return subprocess.run([*prefix, *map(str, argv)], check=True,
                              capture_output=True, timeout=60, **kwargs).stdout

    assert not guest('docker', 'ps', '-q').strip(), 'fixture has running workloads'
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                               ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    uid = guest('id', '-u').decode().strip()
    group = guest('systemctl', '--user', 'show', 'sandbox.slice',
                  '--property=ControlGroup', '--value').decode().strip()
    assert group.endswith(f'/user@{uid}.service/sandbox.slice'), group
    root = Path(tempfile.mkdtemp(prefix='reclaim-fixture-', dir=args.work))
    root.chmod(0o755)  # Production helpers run as the unprivileged container UID.
    image_tag = 'reclaim-fixture:' + uuid.uuid4().hex

    def sample(stage):
        host = subprocess.check_output(['sysctl', '-n', 'kern.num_files'], text=True)
        limit = subprocess.check_output(['sysctl', '-n', 'kern.maxfiles'], text=True)
        assert int(host) < int(limit) * 0.9, 'host pressure guard'
        time.sleep(0.2)
        count = descriptor_count(lib, args.vz_pid)
        print(json.dumps({'stage': stage, 'descriptors': count}), flush=True)
        return count

    def reclaim(target):
        # The diagnostic explicitly chooses an ancestor; the production helper
        # derives its fixed target from its user-manager membership instead.
        result = guest('python3', root / 'reclaim-corpus.py', target)
        print(result.decode().strip(), flush=True)

    try:
        shutil.copyfile(ROOT / 'tests/docker_reclaim_probe.py', root / 'probe.py')
        shutil.copyfile(ROOT / 'tests/reclaim_ancestor_probe.py', root / 'reclaim-corpus.py')
        shutil.copyfile(ROOT / 'tests/fixtures/reclaim.Dockerfile', root / 'Dockerfile')
        for kind in ('workload', 'helper', 'builder'):
            corpus = root / kind
            corpus.mkdir()
            for index in range(512):
                (corpus / str(index)).write_bytes(b'x' * 4096)
            before = sample(kind + '-before')
            if kind == 'builder':
                guest('docker', 'build', '--no-cache', '--network=none',
                      '--build-arg', 'BASE=' + args.image, '-t', image_tag, root)
            elif kind == 'helper':
                print(guest('python3', ROOT / 'tests/reclaim_proxy_fixture.py',
                            '--repo', root, '--image', args.image).decode(), flush=True)
            else:
                guest('docker', 'run', '--rm', '--network=none',
                      '--cgroup-parent=sandbox.slice', '--entrypoint=python3',
                      '--mount', f'type=bind,src={root},dst={root}',
                      args.image, root / 'probe.py', 'read', corpus)
            populated = sample(kind + '-populated')
            assert not guest('docker', 'ps', '-q').strip()
            reclaim('/sys/fs/cgroup' + group)
            after_parent = sample(kind + '-parent-reclaim')
            daemon = guest('systemctl', '--user', 'show', 'docker.service',
                           '--property=ControlGroup', '--value').decode().strip()
            reclaim('/sys/fs/cgroup' + daemon)
            after_daemon = sample(kind + '-daemon-reclaim')
            print(json.dumps({'kind': kind, 'retained': populated - before,
                              'parent_released': populated - after_parent,
                              'daemon_released': after_parent - after_daemon}), flush=True)
            if kind != 'builder':
                assert populated - before >= 450, 'corpus did not retain expected inodes'
                assert populated - after_parent >= 450, 'container parent missed corpus'
    finally:
        try:
            subprocess.run([*prefix, 'docker', 'image', 'rm', '-f', image_tag],
                           capture_output=True, timeout=30, check=False)
        finally:
            shutil.rmtree(root)


if __name__ == '__main__':
    main()
