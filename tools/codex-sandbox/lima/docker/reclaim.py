#!/usr/bin/python3
"""Reclaim one batch from the sandbox slice; never retry in the worker."""

import argparse
from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import stat


@contextmanager
def exclusive(runtime):
    # Keep the inode for the whole boot. Unlinking it lets a replacement worker
    # acquire a different lock while an uninterruptible writer retains this one.
    fd = os.open(runtime / 'sandbox-reclaim.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('reclaim lock is not an owned regular file')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def container_group():
    line = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
                if line.startswith('0::/'))
    current = Path('/sys/fs/cgroup') / line[4:]
    for parent in current.parents:
        if parent.name == f'user@{os.getuid()}.service':
            return parent / 'sandbox.slice'
    raise ValueError('reclaim must run under the guest user manager')


def reclaim(group, runtime, amount):
    if not 0 < amount <= 1024 ** 3:
        raise ValueError('reclaim batch must be 1..1073741824 bytes')
    with exclusive(runtime):
        # Open only after acquiring the lock. Do not move this write into a
        # child whose lifetime could outlast the lock-owning process.
        try:
            with (group / 'memory.reclaim').open('w') as stream:
                stream.write(str(amount))
        except OSError as error:
            if error.errno != errno.EAGAIN:
                raise
            return {'result': 'partial', 'requested_bytes': amount}
        return {'result': 'completed', 'requested_bytes': amount}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-idle', action='store_true')
    parser.add_argument('--bytes', type=int)
    args = parser.parse_args()
    runtime = Path('/run/user') / str(os.getuid())
    if args.check_idle == (args.bytes is not None):
        parser.error('choose --check-idle or --bytes')
    try:
        if args.check_idle:
            with exclusive(runtime):
                result = {'result': 'idle'}
        else:
            result = reclaim(container_group(), runtime, args.bytes)
    except BlockingIOError:
        print(json.dumps({'result': 'busy'}), flush=True)
        raise SystemExit(75)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
