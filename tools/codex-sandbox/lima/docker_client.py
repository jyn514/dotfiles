"""Own the host Buildx executable independently of Homebrew plugin discovery."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile

from lima.host import atomic_json, private_directory

BUILDX_VERSION = 'v0.37.0'
BUILDX_SOURCE = Path('/opt/homebrew/lib/docker/cli-plugins/docker-buildx')


def pin_buildx(state, source=BUILDX_SOURCE):
    source = source.resolve(strict=True)
    client = private_directory(state / 'client')
    with tempfile.TemporaryDirectory(prefix='.pin-buildx-', dir=client) as temporary:
        staged = Path(temporary) / 'docker-buildx'
        shutil.copyfile(source, staged)
        staged.chmod(0o500)
        # Validate the copied artifact, so a concurrent Homebrew upgrade cannot
        # separate the version check from the bytes we publish.
        version = subprocess.run([str(staged), 'version'], check=True, capture_output=True,
                                 text=True, timeout=10).stdout.split()
        if version[:2] != ['github.com/docker/buildx', BUILDX_VERSION]:
            raise ValueError('host Buildx must be ' + BUILDX_VERSION)
        checksum = hashlib.sha256(staged.read_bytes()).hexdigest()
        directory = private_directory(client / 'buildx' / checksum)
        os.replace(staged, directory / 'docker-buildx')
    atomic_json(client / 'buildx.json', {'schema': 1, 'version': BUILDX_VERSION, 'sha256': checksum})
    return verify_buildx(state)


def verify_buildx(state):
    try:
        record = json.loads((state / 'client/buildx.json').read_text())
        if (record['schema'] != 1 or record['version'] != BUILDX_VERSION or
                not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
            raise ValueError('unsupported Buildx record')
        path = state / 'client/buildx' / record['sha256'] / 'docker-buildx'
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o022 or not info.st_mode & stat.S_IXUSR or
                hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']):
            raise ValueError('pinned Buildx changed')
        return path
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('host Buildx is missing or changed; run python3 tools/codex-sandbox/lima/docker_host.py '
                         '--state ' + shlex.quote(str(state)) + ' pin-buildx') from error
