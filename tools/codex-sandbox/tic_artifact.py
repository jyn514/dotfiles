"""Resolve the owned native/broker/Linux-client bundle, never container images."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile

# The subsystem owns one bundle grammar shared by its builder and this launcher.
ROOT = Path(__file__).resolve().parents[1] / 'tic-proxy'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from bundle import (PIN, build_identity, host_platform, protected_bundle, stage_cache,
                    validate_bundle)


def _source_setting(home: Path, writable_roots):
    """Read the one host-only machine path; no project/environment override."""
    path = Path(home) / '.config/codex-sandbox/tic-native-source'
    if not path.exists():
        raise ValueError('TicGit cold cache requires a trusted native repository path in ' + str(path)
                         + '; start Pi once with --set-tic-native-source PATH')
    if path.resolve(strict=True) != path:
        raise ValueError('TicGit native-source setting must be a canonical regular file')
    if any(path.is_relative_to(Path(root).resolve(strict=True)) for root in writable_roots):
        raise ValueError('TicGit native-source setting must not be guest-writable')
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise ValueError('TicGit native-source setting must be launcher-owned, single-link, mode 0600')
        raw = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    if len(raw) > 4096:
        raise ValueError('TicGit native-source setting exceeds 4096 bytes')
    value = raw.decode('utf-8').removesuffix('\n')
    if not value or any(character in value for character in ('\0', '\n', '\r')):
        raise ValueError('TicGit native-source setting must contain one absolute repository path')
    source = Path(value)
    if not source.is_absolute():
        raise ValueError('TicGit native-source setting must contain an absolute repository path')
    return source


def native_source(home: Path, writable_roots):
    source = _source_setting(home, writable_roots)
    if not source.is_dir():
        raise ValueError('TicGit native-source setting must name an existing repository directory')
    return source.resolve(strict=True)


def configure_native_source(home: Path, repository: Path, *, replace=False):
    """Set one known host field explicitly, never alter unrelated configuration."""
    repository = Path(repository).expanduser().resolve(strict=True)
    if not repository.is_dir():
        raise ValueError('TicGit native source must be a repository directory')
    encoded = (str(repository) + '\n').encode('utf-8')
    if len(encoded) > 4096 or any(character in str(repository) for character in ('\0', '\n', '\r')):
        raise ValueError('TicGit native source path is not representable in the host setting')
    result = subprocess.run(['git', '-C', str(repository), 'rev-parse', PIN + '^{commit}'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    if result.stdout.strip() != PIN:
        raise ValueError('TicGit native source does not contain the pinned commit')
    path = Path(home) / '.config/codex-sandbox/tic-native-source'
    exists = path.exists() or path.is_symlink()
    if exists:
        previous = _source_setting(home, ()).resolve()
        if previous == repository:
            return path
        if not replace:
            raise ValueError('existing TicGit native-source setting differs; refusing to overwrite host configuration')
    if path.parent.resolve() != path.parent:
        raise ValueError('TicGit native-source setting directory must be canonical')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.parent.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
        raise ValueError('TicGit native-source setting directory has unsafe ownership/permissions')
    descriptor, temporary = tempfile.mkstemp(prefix='.tic-native-source-', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            os.fchmod(stream.fileno(), 0o600)
        if exists and replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass  # Validate a concurrent publisher below; never replace it.
    finally:
        temporary.unlink(missing_ok=True)
    if native_source(home, ()) != repository:
        raise ValueError('existing TicGit native-source setting differs; refusing to overwrite host configuration')
    return path


def build_bundle(native_repository: Path, expected):
    """Use the ordinary pinned builder on a cold cache, not a test starter."""
    result = subprocess.run([sys.executable, str(ROOT / 'build-local'),
                             '--guest-platform', expected['guest_platform'],
                             str(native_repository), 'build', '--bins'],
                            stdout=subprocess.PIPE, text=True, check=True)
    paths = [line.removeprefix('staged bundle: ') for line in result.stdout.splitlines()
             if line.startswith('staged bundle: ')]
    if len(paths) != 1:
        raise ValueError('TicGit builder did not return one staged bundle')
    bundle = Path(paths[0])
    validate_bundle(bundle, expected)
    return bundle


def resolve_bundle(cache: Path, guest_platform: str, writable_roots, provision, *, local_bundle=None):
    """Resolve exactly the current source key; a miss invokes the owned builder.

    The local development override follows the identical validation/copy path.
    A malformed/partial existing key is an error, never adopted or repaired.
    """
    expected = build_identity(host_platform(), guest_platform)
    key = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    cache = Path(cache).absolute()
    if cache.resolve() != cache:
        raise ValueError('TicGit cache must be canonical, not a symlink alias')
    for root in writable_roots:
        root = Path(root).resolve(strict=True)
        if cache.is_relative_to(root) or root.is_relative_to(cache):
            raise ValueError('TicGit cache overlaps a guest-writable mount')
    if cache.exists():
        metadata = cache.lstat()
        if not cache.is_dir() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise ValueError('TicGit cache ownership/mode mismatch')
    cache.parent.mkdir(parents=True, exist_ok=True)
    parent = cache.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
        raise ValueError('TicGit cache parent ownership/mode mismatch')
    cache.mkdir(mode=0o700, exist_ok=True)
    # Same flock publication rule as the launcher's SessionLock, without any
    # shared-service lifetime state. Hold through build and final cache copy.
    descriptor = os.open(cache / '.resolve.lock', os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
                         | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'r+b') as lock:
        metadata = os.fstat(lock.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise ValueError('TicGit cache lock ownership/mode/link mismatch')
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _resolve_locked(cache, key, expected, writable_roots, provision, local_bundle)


def _resolve_locked(cache, key, expected, writable_roots, provision, local_bundle):
    destination = cache / key
    if destination.exists() or destination.is_symlink():
        metadata = destination.lstat()
        if (destination.is_symlink() or not destination.is_dir()
                or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022):
            raise ValueError('invalid TicGit cache source-key directory')
        entries = list(destination.iterdir())
        if len(entries) != 1:
            raise ValueError('partial or ambiguous TicGit cache source key')
        bundle = entries[0]
        encoded, _, _ = protected_bundle(bundle, expected)
        if local_bundle is not None:
            local_encoded, _, _ = validate_bundle(Path(local_bundle).resolve(strict=True), expected)
            if local_encoded != encoded:
                raise ValueError('local TicGit bundle differs from existing source-key cache')
        return bundle / 'manifest.json'
    # Provision before creating a cache key: failed builds leave no accepted state.
    bundle = Path(local_bundle) if local_bundle is not None else Path(provision(expected))
    validate_bundle(bundle.resolve(strict=True), expected)
    # Publish the whole populated source key, never an empty key or in-flight
    # .tic-cache-* copy that another normal launch could mistake for authored
    # partial state. TemporaryDirectory owns cleanup only for this private key.
    with tempfile.TemporaryDirectory(prefix='.tic-key-', dir=cache) as private:
        private = Path(private)
        manifest = stage_cache(bundle, private, writable_roots, expected=expected)
        relative = manifest.relative_to(private)
        if destination.exists() or destination.is_symlink():
            raise ValueError('TicGit cache key appeared during publication; refusing overwrite')
        os.rename(private, destination)
        return destination / relative

