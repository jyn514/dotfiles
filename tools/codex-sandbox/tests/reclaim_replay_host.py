"""Run the disposable replay with externally sampled file-table headroom."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from file_pressure import sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--replay-image', required=True)
    parser.add_argument('--vz-pid', type=int, required=True)
    args = parser.parse_args()
    record = json.loads((args.state / 'host.json').read_text())
    assert record['instance'].startswith('sandbox-host-docker-')
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                               ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    prefix = ['limactl', 'shell', record['instance']]
    command = [*prefix, 'python3', str(ROOT / 'tests/docker_reclaim_lifecycle.py'),
               '--record', '-', '--image', args.image, '--work', str(args.work),
               '--replay-image', args.replay_image]
    with (args.work / 'replay-lifecycle.log').open('w') as output, \
            (args.work / 'replay-host.jsonl').open('w') as samples:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.stdin.write(json.dumps(record).encode())
            process.stdin.close()
            while process.poll() is None:
                started = time.monotonic()
                observation = sample(lib)
                vm = next(item for item in observation['virtual_machines'] if item['pid'] == args.vz_pid)
                if 'descriptors' not in vm:
                    raise RuntimeError('fixture descriptor observation unavailable')
                host = observation['host']
                observation['fixture_headroom'] = 1 - vm['descriptors'] / host['kern.maxfilesperproc']
                observation['global_headroom'] = 1 - host['kern.num_files'] / host['kern.maxfiles']
                print(json.dumps(observation), file=samples, flush=True)
                if min(observation['fixture_headroom'], observation['global_headroom']) < 0.10:
                    raise RuntimeError('replay aborted at 10% headroom')
                time.sleep(max(0, 0.1 - (time.monotonic() - started)))
            if process.wait() != 0:
                raise RuntimeError('lifecycle/replay failed; inspect replay-lifecycle.log')
        finally:
            if process.poll() is None:
                # Stop the owned workload first so the remote fixture can
                # execute its configuration-restoration finally block.
                subprocess.run([*prefix, 'docker', 'rm', '-f', 'reclaim-replay-cycle'],
                               timeout=30, check=False, stdout=output, stderr=output)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)


if __name__ == '__main__':
    main()
