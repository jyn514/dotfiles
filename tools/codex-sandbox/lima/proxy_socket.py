"""Guest-side, session-owned short names for proxy sockets."""

import os
from pathlib import Path
import re
import stat
import sys


def directory(owner):
    if not isinstance(owner, str) or not re.fullmatch('[0-9a-f]{32}', owner):
        raise ValueError('invalid proxy socket owner')
    return Path('/tmp') / ('codex-proxy-' + owner)


def private(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('proxy socket directory ownership changed')


def alias(operation, owner, target):
    path = directory(owner)
    target = Path(target)
    if not target.is_absolute() or '..' in target.parts:
        raise ValueError('proxy socket target must be absolute')
    if operation == 'create':
        # The optional server may not have bound its socket yet.
        path.mkdir(mode=0o700, exist_ok=True)
    elif operation != 'remove':
        raise ValueError('unknown proxy socket operation')
    elif not path.exists() and not path.is_symlink():
        return
    private(path)
    socket = path / 's'
    if socket.is_symlink():
        if os.readlink(socket) != str(target):
            raise ValueError('proxy socket target changed')
    elif socket.exists():
        raise ValueError('proxy socket alias was replaced')
    elif operation == 'create':
        socket.symlink_to(target)
    if operation == 'remove':
        socket.unlink(missing_ok=True)
        path.rmdir()


if __name__ == '__main__':
    alias(*sys.argv[1:])
