"""One relative bundle manifest for local builds and launcher-owned cache snapshots."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


ROOT = Path(__file__).resolve().parent
PIN = (ROOT / "native-revision").read_text().strip()
if re.fullmatch(r"[0-9a-f]{40}", PIN) is None:
    raise ValueError("invalid canonical native-revision input")


def guest_platform(path):
    with path.open('rb') as stream:
        header = stream.read(64)
    if len(header) < 64 or header[:4] != b'\x7fELF' or header[4:6] != b'\x02\x01':
        raise ValueError('guest client must be a 64-bit little-endian Linux ELF, not a host Mach-O binary')
    # System-V (0) or Linux (3) ABI; static musl artifacts normally use System-V.
    if header[7] not in (0, 3):
        raise ValueError('unsupported guest ELF ABI')
    arch = {62: 'linux/amd64', 183: 'linux/arm64'}.get(int.from_bytes(header[18:20], 'little'))
    if arch is None:
        raise ValueError('unsupported Linux guest architecture')
    # Only static clients are portable into the guest image; an arbitrary ELF
    # interpreter path does not establish that the provider image can execute it.
    offset = int.from_bytes(header[32:40], 'little')
    entry_size = int.from_bytes(header[54:56], 'little')
    count = int.from_bytes(header[56:58], 'little')
    if not 56 <= entry_size <= 256 or count > 1024:
        raise ValueError('invalid guest ELF program headers')
    with path.open('rb') as stream:
        stream.seek(offset)
        for _ in range(count):
            entry = stream.read(entry_size)
            if len(entry) != entry_size:
                raise ValueError('truncated guest ELF program headers')
            if int.from_bytes(entry[:4], 'little') == 3:
                raise ValueError('guest client must be statically linked (ELF PT_INTERP is unsupported)')
    return arch


ARTIFACTS = {'native': 'native/ti', 'broker': 'host/tic-broker', 'client': 'guest/ti-proxy'}
DIRECTORIES = ('native', 'host', 'guest')
FILES = (*ARTIFACTS.values(), 'native/ti.tic-proxy.json', 'manifest.json')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate manifest field')
        value[key] = item
    return value


def regular(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError('bundle artifact must be a regular file, not a symlink')
    return metadata


def read_json(path):
    regular(path)
    with path.open('rb') as stream:
        encoded = stream.read(65537)
    if len(encoded) > 65536:
        raise ValueError('manifest exceeds 64 KiB')
    value = json.loads(encoded, object_pairs_hook=strict_object)
    if not isinstance(value, dict):
        raise ValueError('manifest must be an object')
    return encoded, value


def tree(root, protected=False):
    # Fixed tree grammar rejects symlinked ancestor directories as well as leaf
    # symlinks. Build outputs may be writable; protected copies must not be.
    for relative in ('', *DIRECTORIES):
        directory = root / relative
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError('bundle directories must not be symlinks')
        if protected and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o555):
            raise ValueError('protected bundle directory ownership/mode mismatch')
        expected = ({'manifest.json', *DIRECTORIES} if not relative else
                    {Path(name).name for name in FILES if Path(name).parent == Path(relative)})
        if {path.name for path in directory.iterdir()} != expected:
            raise ValueError('unexpected or missing bundle entries')
    for relative in FILES:
        metadata = regular(root / relative)
        if protected:
            mode = 0o555 if relative in ARTIFACTS.values() else 0o444
            if (metadata.st_uid != os.getuid() or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) != mode):
                raise ValueError('protected artifact ownership/mode/link mismatch')


def native_binding(path, native_hash):
    encoded, value = read_json(path)
    if (set(value) != {'native_revision', 'policy_version', 'sha256'}
            or type(value['policy_version']) is not int or value['policy_version'] != 1
            or value['native_revision'] != PIN or value['sha256'] != native_hash):
        raise ValueError('native manifest binding mismatch')
    return encoded


def _bundle_metadata(bundle, expected=None, *, protected=False):
    tree(bundle, protected=protected)
    encoded, manifest = read_json(bundle / 'manifest.json')
    if set(manifest) != {'version', 'native_revision', 'policy_version', 'native', 'broker', 'client', 'build'}:
        raise ValueError('unexpected bundle fields')
    if (type(manifest['version']) is not int or manifest['version'] != 2
            or type(manifest['policy_version']) is not int or manifest['policy_version'] != 1
            or manifest['native_revision'] != PIN):
        raise ValueError('unsupported native/policy binding')
    validate_identity(manifest['build'])
    if expected is not None and manifest['build'] != expected:
        raise ValueError('bundle does not match current proxy sources/native/policy/platform')
    if manifest['build']['guest_platform'] != manifest['client']['platform']:
        raise ValueError('bundle guest platform/build mismatch')
    identity = 'bundle-' + hashlib.sha256(encoded).hexdigest()
    if bundle.name != identity:
        raise ValueError('content-addressed bundle name/manifest mismatch')
    for key, relative in ARTIFACTS.items():
        artifact = manifest[key]
        fields = {'path', 'sha256', 'platform'} if key == 'client' else {'path', 'sha256'}
        if not isinstance(artifact, dict) or set(artifact) != fields or artifact['path'] != relative:
            raise ValueError('unexpected artifact path or fields')
        if not isinstance(artifact['sha256'], str) or re.fullmatch(r'[0-9a-f]{64}', artifact['sha256']) is None:
            raise ValueError('invalid bundle artifact digest')
    if guest_platform(bundle / ARTIFACTS['client']) != manifest['client']['platform']:
        raise ValueError('guest artifact/platform mismatch')
    binding = native_binding(bundle / 'native/ti.tic-proxy.json', manifest['native']['sha256'])
    return encoded, manifest, binding


def protected_bundle(bundle, expected=None):
    """Read a published launcher-owned snapshot, without rehashing executables.

    Publication verifies bytes. Runtime authority is the protected tree outside
    guest-writable mounts, not detection of a host rewriting its own cache.
    Incoming development/build output must use validate_bundle instead.
    """
    bundle = Path(bundle)
    if not bundle.is_absolute() or bundle.resolve(strict=True) != bundle:
        raise ValueError('protected bundle must be canonical and absolute')
    return _bundle_metadata(bundle, expected, protected=True)


def validate_bundle(bundle, expected=None):
    """Fully verify incoming build output before copying/publication."""
    encoded, manifest, binding = _bundle_metadata(bundle, expected)
    for key, relative in ARTIFACTS.items():
        if manifest[key]['sha256'] != sha256(bundle / relative):
            raise ValueError('bundle artifact hash mismatch')
    return encoded, manifest, binding


def verify_copy(destination, encoded, manifest, binding):
    tree(destination, protected=True)
    if (destination / 'manifest.json').read_bytes() != encoded:
        raise ValueError('existing protected bundle manifest mismatch')
    for key, relative in ARTIFACTS.items():
        if sha256(destination / relative) != manifest[key]['sha256']:
            raise ValueError('protected artifact hash mismatch')
    if native_binding(destination / 'native/ti.tic-proxy.json', manifest['native']['sha256']) != binding:
        raise ValueError('protected native binding changed')


def remove_stage(stage):
    # Only a private stage created by this invocation; never repair an existing
    # cache entry's modes or take ownership of mismatched content.
    for relative in ('', *DIRECTORIES):
        path = stage / relative
        if path.is_dir():
            path.chmod(0o700)
    shutil.rmtree(stage)


def stage_cache(bundle, prefix, guest_writable_roots=(), *, expected=None):
    bundle = Path(bundle).resolve(strict=True)
    encoded, manifest, binding = validate_bundle(bundle, expected)
    prefix = Path(prefix).absolute()
    if prefix.resolve() != prefix:
        raise ValueError('cache staging root must be canonical, not a symlink alias')
    for root in guest_writable_roots:
        root = Path(root).resolve(strict=True)
        if prefix.is_relative_to(root) or root.is_relative_to(prefix):
            raise ValueError('cache staging root overlaps a guest-writable mount')
    parent = prefix.parent.resolve(strict=True)
    for directory in (parent, prefix) if prefix.exists() else (parent,):
        metadata = directory.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o022):
            raise ValueError('cache root/parent must belong to the launcher user and not be group/world writable')
    created_root = not prefix.exists()
    if created_root:
        prefix.mkdir(mode=0o700)
    destination = prefix / bundle.name
    stage = None
    reserved = False
    try:
        if destination.exists() or destination.is_symlink():
            verify_copy(destination, encoded, manifest, binding)
        else:
            stage = Path(tempfile.mkdtemp(prefix='.tic-cache-', dir=prefix))
            for key, relative in ARTIFACTS.items():
                target = stage / relative
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(bundle / relative, target)
                if sha256(target) != manifest[key]['sha256']:
                    raise ValueError('artifact changed during cache staging')
                target.chmod(0o555)
            shutil.copyfile(bundle / 'native/ti.tic-proxy.json', stage / 'native/ti.tic-proxy.json')
            if native_binding(stage / 'native/ti.tic-proxy.json', manifest['native']['sha256']) != binding:
                raise ValueError('native binding changed during cache staging')
            (stage / 'native/ti.tic-proxy.json').chmod(0o444)
            (stage / 'manifest.json').write_bytes(encoded)
            (stage / 'manifest.json').chmod(0o444)
            for relative in ('', *DIRECTORIES):
                (stage / relative).chmod(0o555)
            verify_copy(stage, encoded, manifest, binding)
            # Reserve an absent destination exclusively. Never rename over an
            # existing directory, even an empty mismatched cache entry.
            destination.mkdir(mode=0o700)
            reserved = True
            os.rename(stage, destination)  # replaces only our empty reservation
            reserved = False
            stage = None
        verify_copy(destination, encoded, manifest, binding)
        return destination / 'manifest.json'
    finally:
        if stage is not None:
            remove_stage(stage)
        if reserved:
            destination.rmdir()
        if created_root:
            try:
                prefix.rmdir()  # only remove our root if still empty
            except OSError:
                pass



def source_identity(root=ROOT):
    """Hash the bounded build inputs, not mtimes or checkout location."""
    paths = [Path(name) for name in ('Cargo.toml', 'Cargo.lock', 'native-revision',
                                    'build-local', 'bundle.py')]
    paths += [path.relative_to(root) for path in (root / 'src').rglob('*.rs')]
    identity = hashlib.sha256()
    for path in sorted(paths):
        identity.update(os.fsencode(path.as_posix()) + b'\0')
        identity.update(hashlib.sha256((root / path).read_bytes()).digest())
    return identity.hexdigest()


def build_identity(host_platform, guest_platform, root=ROOT):
    return dict(proxy_source=source_identity(root), native_revision=(root / 'native-revision').read_text().strip(),
                policy_version=1, wire_version=2, host_platform=host_platform, guest_platform=guest_platform)


def validate_identity(value):
    if (not isinstance(value, dict) or set(value) != {'proxy_source', 'native_revision', 'policy_version',
                                                   'wire_version', 'host_platform', 'guest_platform'}
            or not isinstance(value['proxy_source'], str)
            or re.fullmatch('[0-9a-f]{64}', value['proxy_source']) is None
            or value['native_revision'] != PIN
            or type(value['policy_version']) is not int or value['policy_version'] != 1
            or type(value['wire_version']) is not int or value['wire_version'] != 2
            or value['host_platform'] not in ('linux/amd64', 'linux/arm64', 'darwin/amd64', 'darwin/arm64')
            or value['guest_platform'] not in ('linux/amd64', 'linux/arm64')):
        raise ValueError('unsupported bundle build identity')


def host_platform():
    import platform
    system = {'Linux': 'linux', 'Darwin': 'darwin'}.get(platform.system())
    machine = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if system is None or machine is None:
        raise ValueError('unsupported TicGit host platform')
    return system + '/' + machine
