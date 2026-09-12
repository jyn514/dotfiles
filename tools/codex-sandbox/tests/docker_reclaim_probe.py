"""Bounded guest filesystem workload for the reclamation fixture."""

import json
import os
from pathlib import Path
import sys
import time


def main():
    operation, directory = sys.argv[1:3]
    root = Path(directory)
    paths = [root / str(index) for index in range(512)]
    if operation in ('read', 'readwait'):
        for path in paths:
            assert path.read_bytes() == b'x' * 4096
        if operation == 'readwait':
            print('ready', flush=True)
            deadline = time.monotonic() + 30
            while not (root.parent / 'release').exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError('fixture did not release the helper')
                time.sleep(0.05)
    elif operation == 'hold':
        streams = [path.open('rb') for path in paths]
        print('ready', flush=True)
        sys.stdin.readline()
        for stream in streams:
            assert stream.read() == b'x' * 4096
            stream.close()
    elif operation == 'write':
        for index, path in enumerate(paths):
            temporary = root / (str(index) + '.new')
            with temporary.open('wb') as stream:
                stream.write(b'x' * 4096)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            assert path.read_bytes() == b'x' * 4096
        fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    elif operation == 'identity':
        print(Path('/proc/self/cgroup').read_text(), end='')
    else:
        raise ValueError(operation)
    print(json.dumps({'operation': operation, 'time': time.monotonic()}), flush=True)


if __name__ == '__main__':
    main()
