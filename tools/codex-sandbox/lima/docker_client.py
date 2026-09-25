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

def default_buildx_source():
    candidates = [
        Path('/opt/homebrew/lib/docker/cli-plugins/docker-buildx'),
        Path('/usr/libexec/docker/cli-plugins/docker-buildx'),
        Path('/usr/lib/docker/cli-plugins/docker-buildx'),
        Path('/usr/local/lib/docker/cli-plugins/docker-buildx'),
        Path.home() / '.docker/cli-plugins/docker-buildx',
    ]
    return next((path for path in candidates if path.is_file()), None)

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
        match = re.match(r'^Docker version ([^,]+),', version)
        if match is None:
            raise ValueError('host Docker CLI must identify itself as Docker')
        checksum = hashlib.sha256(staged.read_bytes()).hexdigest()
        directory = private_directory(client / 'docker' / checksum)
        os.replace(staged, directory / 'docker')
    return {'version': match.group(1), 'sha256': checksum}


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
        if (not isinstance(artifact['version'], str) or
                not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}(?:[-+].*)?', artifact['version']) or
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


def pin_buildx(state, source=None):
    source = source or default_buildx_source()
    if source is None:
        raise ValueError('Docker Buildx plugin is required; install docker-buildx-plugin or pass a source')
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
        if (len(version) < 2 or version[0] != 'github.com/docker/buildx' or
                not re.fullmatch(r'v?[0-9]+(?:\.[0-9]+){2}', version[1])):
            raise ValueError('host Buildx must identify itself as Docker Buildx')
        checksum = hashlib.sha256(staged.read_bytes()).hexdigest()
        directory = private_directory(client / 'buildx' / checksum)
        os.replace(staged, directory / 'docker-buildx')
    atomic_json(client / 'buildx.json', {'schema': 1, 'version': version[1], 'sha256': checksum})
    return verify_buildx(state)


def verify_buildx(state):
    try:
        record = json.loads((state / 'client/buildx.json').read_text())
        if (record['schema'] != 1 or
                not isinstance(record['version'], str) or
                not re.fullmatch(r'v?[0-9]+(?:\.[0-9]+){2}', record['version']) or
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
