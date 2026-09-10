"""Own host Docker executables independently of Homebrew upgrades and discovery."""

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
DOCKER_VERSION = '29.8.0'

# Pinning owns these private copies; Homebrew never updates them. Hash only
# when publishing a copy, not on every command routed through this module.


def pin_docker(state, source):
    """Stage a client; the caller atomically publishes its descriptor in host.json."""
    client = private_directory(state / 'client')
    with tempfile.TemporaryDirectory(prefix='.pin-docker-', dir=client) as temporary:
        staged = Path(temporary) / 'docker'
        shutil.copyfile(Path(source).resolve(strict=True), staged)
        staged.chmod(0o500)
        version = subprocess.run([str(staged), '--version'], check=True,
                                 capture_output=True, text=True, timeout=10).stdout
        if not version.startswith('Docker version ' + DOCKER_VERSION + ','):
            raise ValueError('host Docker CLI must be ' + DOCKER_VERSION)
        checksum = hashlib.sha256(staged.read_bytes()).hexdigest()
        directory = private_directory(client / 'docker' / checksum)
        os.replace(staged, directory / 'docker')
    return {'version': DOCKER_VERSION, 'sha256': checksum}


def docker_client(state, record):
    if 'client_artifact' not in record:
        # Old records retain explicit client selection until pin-client migrates
        # them. Never fall back to PATH if Homebrew removed that executable.
        if not Path(record['client']).is_file():
            raise ValueError('recorded Docker CLI is missing; run python3 tools/codex-sandbox/lima/docker_host.py --state '
                             + shlex.quote(str(state)) + ' pin-client')
        return record['client']
    try:
        artifact = record['client_artifact']
        if (artifact['version'] != DOCKER_VERSION or
                not re.fullmatch('[0-9a-f]{64}', artifact['sha256'])):
            raise ValueError('unsupported Docker client record')
        path = state / 'client/docker' / artifact['sha256'] / 'docker'
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o022 or not info.st_mode & stat.S_IXUSR):
            raise ValueError('pinned Docker client changed')
        return str(path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('host Docker CLI is missing or changed; run python3 tools/codex-sandbox/lima/docker_host.py --state '
                         + shlex.quote(str(state)) + ' pin-client') from error


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
                info.st_mode & 0o022 or not info.st_mode & stat.S_IXUSR):
            raise ValueError('pinned Buildx changed')
        return path
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError('host Buildx is missing or changed; run python3 tools/codex-sandbox/lima/docker_host.py '
                         '--state ' + shlex.quote(str(state)) + ' pin-buildx') from error
