#!/usr/bin/env python3
"""Build pinned Dashboard source plus downstream patches, then reconcile local policy."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = '@blackbelt-technology/pi-agent-dashboard'
SOURCE = ROOT / 'config/pi-dashboard-source.json'
STAMP = '.dotfiles-dashboard-patch.json'
POLICY = ROOT / 'config/pi-dashboard.json'
COMPONENTS = {'server': 'server', 'shared': 'shared', 'extension': 'extension', 'web': 'client'}


def command(*args, env=None):
    return subprocess.run(args, check=True, text=True, capture_output=True, env=env).stdout.strip()


def run(args, *, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def publish(path, contents, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def check_link(path):
    if path.exists() and not path.is_symlink():
        raise ValueError(f'Refusing to replace an existing path: {path}')


def publish_symlink(path, target):
    check_link(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
        replacement = Path(temporary) / path.name
        replacement.symlink_to(target)
        replacement.replace(path)


def source_inputs():
    """Read the pin and ordered patch bytes once, including during a rebuild."""
    value = json.loads(SOURCE.read_text())
    if not isinstance(value, dict) or set(value) != {'repository', 'revision', 'patches'}:
        raise ValueError(f'Expected repository, revision, and patches in {SOURCE}')
    if not isinstance(value['repository'], str) or not value['repository']:
        raise ValueError('Dashboard repository must be a nonempty URL')
    if not isinstance(value['revision'], str) or not re.fullmatch('[0-9a-f]{40}', value['revision']):
        raise ValueError('Dashboard revision must be a full lowercase commit hash')
    if not isinstance(value['patches'], list) or not all(isinstance(p, str) and p for p in value['patches']):
        raise ValueError('Dashboard patches must be an ordered list of paths')
    patches = [(name, (ROOT / name).read_bytes()) for name in value['patches']]
    return value, patches


def patch_receipts(patches):
    return [{'path': name, 'sha256': digest(contents)} for name, contents in patches]


def clone(entry, destination):
    # Use the existing locked-source acquisition owner, with this subsystem's pin.
    bootstrap = runpy.run_path(str(ROOT / 'libexec/setup/install_bootstrap.py'))
    bootstrap['clone'](entry, destination)


def component_roots(core):
    result = command('node', str(ROOT / 'libexec/setup/setup_dashboard_roots.mjs'), str(core))
    return {name: [Path(path) for path in paths] for name, paths in json.loads(result).items()}


def validate_source(core):
    metadata = json.loads((core / 'package.json').read_text())
    if metadata.get('name') != PACKAGE:
        raise ValueError(f'Not a Dashboard source checkout: {core}')
    if not re.fullmatch(r'pnpm@[0-9]+\.[0-9]+\.[0-9]+', metadata.get('packageManager', '')):
        raise ValueError('Dashboard source must pin its pnpm packageManager')
    if 'packages/extension/src/bridge.ts' not in metadata.get('pi', {}).get('extensions', []):
        raise ValueError('Dashboard source does not publicly declare its bridge')
    for relative in ('pnpm-lock.yaml', 'pnpm-workspace.yaml', 'packages/extension/src/bridge.ts',
                     'packages/server/bin/pi-dashboard.mjs', 'packages/server/src/cli.ts'):
        if not (core / relative).is_file():
            raise ValueError(f'Dashboard source is missing {relative}: {core}')
    for name, directory in COMPONENTS.items():
        manifest = json.loads((core / f'packages/{directory}/package.json').read_text())
        if manifest.get('name') != f'@blackbelt-technology/pi-dashboard-{name}':
            raise ValueError(f'Unexpected Dashboard workspace package: {directory}')


def validate_workspace(core):
    validate_source(core)
    for name, roots in component_roots(core).items():
        if roots != [(core / 'packages' / COMPONENTS[name]).resolve()]:
            raise ValueError(f'Dashboard {name} must resolve to the built workspace, not registry packages')
    if not (core / 'packages/client/dist/index.html').is_file():
        raise ValueError('Dashboard browser build is missing')


def runtime_files(core):
    paths = [core / 'package.json', core / 'pnpm-lock.yaml', core / 'pnpm-workspace.yaml']
    for directory in COMPONENTS.values():
        paths.append(core / f'packages/{directory}/package.json')
    for relative in ('packages/server/src', 'packages/server/bin', 'packages/shared/src',
                     'packages/extension/src', 'packages/client/dist'):
        paths.extend(path for path in (core / relative).rglob('*') if path.is_file())
    return {str(path.relative_to(core)): digest(path.read_bytes()) for path in sorted(paths)}


def validate_build(core):
    validate_workspace(core)
    receipt = json.loads((core / STAMP).read_text())
    if not isinstance(receipt, dict):
        raise ValueError('Dashboard build receipt must be an object')
    _, patches = source_inputs()
    if receipt.get('patches') != patch_receipts(patches):
        raise ValueError('Dashboard patches changed; rerun ./setup dashboard to rebuild')
    if receipt.get('files') != runtime_files(core):
        raise ValueError('Dashboard build is not intact; rerun ./setup dashboard to rebuild')
    return receipt


def native_patch(stage, patch):
    args = ['patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '--reject-file=-',
            '-p1', '-d', str(stage), '-i', str(patch), '--forward']
    command(*args, '--dry-run')
    command(*args)


def copy_checkout(checkout, destination):
    # Git selects tracked files (including edits) and non-ignored untracked
    # files. A directory's name alone cannot tell source from build output.
    listing = subprocess.run(['git', '-C', str(checkout), 'ls-files', '--cached',
                              '--others', '--exclude-standard', '-z'],
                             check=True, capture_output=True).stdout
    destination.mkdir()
    for name in sorted(set(listing.split(b'\0')) - {b''}):
        relative = Path(os.fsdecode(name))
        source = checkout / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', '.jj', 'node_modules'))
        elif source.exists():
            # Dereference input symlinks: patches/builds must only write copies.
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def build_source(checkout=None, home=None):
    """Build in owned storage; never patch, install, or build in the input checkout.

    Return a complete workspace without changing active links or runtime policy.
    A checkout supplies current tracked and non-ignored untracked files, not
    HEAD. Managed builds reuse an intact matching pin.
    """
    home = home if home is not None else Path.home()
    specification, patches = source_inputs()
    source = {'repository': specification['repository'], 'revision': specification['revision']}
    state = home / '.local/share/pi-dashboard'
    current = state / 'current'
    if checkout is None and current.is_symlink():
        core = current.resolve()
        try:
            receipt = validate_build(core)
        except (OSError, ValueError, subprocess.SubprocessError):
            # Build a replacement without touching the damaged active tree.
            pass
        else:
            if receipt.get('source') == source and receipt.get('patches') == patch_receipts(patches):
                return core
    if checkout is not None:
        checkout = Path(checkout).expanduser().resolve(strict=True)
        validate_source(checkout)
        source = {'checkout': str(checkout)}
    builds = state / 'builds'
    builds.mkdir(parents=True, exist_ok=True)
    generation = Path(tempfile.mkdtemp(prefix='build-', dir=builds))
    core = generation / 'source'
    try:
        if checkout is None:
            print(f"Dashboard: acquire upstream {specification['revision'][:12]}", file=sys.stderr)
            clone({'url': specification['repository'], 'revision': specification['revision']}, core)
            shutil.rmtree(core / '.git')
        else:
            print(f'Dashboard: copy checkout {checkout}', file=sys.stderr)
            copy_checkout(checkout, core)
        validate_source(core)
        # Freeze patch bytes as well as source; editing dotfiles during a long
        # build cannot change which patch a later step applies.
        for index, (name, contents) in enumerate(patches):
            print(f'Dashboard: apply {name}', file=sys.stderr)
            patch = generation / f'{index}.patch'
            patch.write_bytes(contents)
            native_patch(core, patch)
        print('Dashboard: install locked dependencies and build', file=sys.stderr)
        environment = os.environ.copy()
        # The workspace's prepare scripts build the browser during installation too.
        environment['NODE_OPTIONS'] = (environment.get('NODE_OPTIONS', '') + ' --max-old-space-size=4096').strip()
        run(['pnpm', 'install', '--frozen-lockfile'], cwd=core, env=environment)
        run(['pnpm', 'run', 'build'], cwd=core, env=environment)
        validate_workspace(core)
        publish(core / STAMP, (json.dumps({
            'source': source, 'patches': patch_receipts(patches), 'files': runtime_files(core),
        }, indent=2) + '\n').encode())
        return core
    except BaseException:
        shutil.rmtree(generation)
        raise


def activate(core, home):
    current = home / '.local/share/pi-dashboard/current'
    launcher = home / '.local/bin/pi-dashboard'
    bridge = home / '.pi/agent/pi-dashboard'
    check_link(current)
    check_link(launcher)
    check_link(bridge)
    publish_symlink(launcher, ROOT / 'bin/pi-dashboard')
    publish_symlink(current, core)
    # Migrate an already-enabled release bridge even for --install-only.
    # A fresh package installation must not enable a bridge or require policy.
    if bridge.is_symlink():
        publish_symlink(bridge, current)


def read_object(path):
    if path.is_symlink():
        raise ValueError(f'Dashboard runtime state must be a local real file: {path}')
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def object_field(value, key):
    field = value.setdefault(key, {})
    if not isinstance(field, dict):
        raise ValueError(f'Expected a JSON object for {key}')
    return field


def tailnet_ipv4(value):
    address = ipaddress.IPv4Address(value)
    if address not in ipaddress.IPv4Network('100.64.0.0/10'):
        raise ValueError('Dashboard requires this machine\'s Tailscale IPv4 in 100.64.0.0/10')
    return str(address)


def tailscale_address():
    try:
        status = json.loads(command('tailscale', 'status', '--json'))
        if status.get('BackendState') != 'Running' or status.get('Self', {}).get('Online') is not True:
            raise ValueError('Tailscale is not connected')
        return tailnet_ipv4(command('tailscale', 'ip', '-4').strip())
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError) as error:
        raise RuntimeError('Connect the native Tailscale client on this host, then rerun ./setup services; '
                           'Dashboard will not fall back to localhost or all interfaces') from error


def apply_policy(config):
    """Merge only source-owned policy fields; machine state remains local."""
    policy = json.loads(POLICY.read_text())
    scalars = {'spawnStrategy': str, 'spawnRegisterTimeoutMs': int,
               'autoShutdown': bool, 'registerAskUserTool': bool,
               'listenOnLoopback': bool, 'maxConcurrentSubagents': int,
               'defaultModel': str, 'defaultThinkingLevel': str,
               'reopenSessionsAfterShutdown': str}
    objects = {'agentPathGate': {'enabled': bool}, 'openspec': {'enabled': bool},
               'vault': {'deliveryEnabled': bool},
               'piTrustMirror': {'enabled': bool, 'liveQuery': bool},
               'accessGrants': {'promptEnabled': bool}, 'questions': {'autoBrief': bool},
               'modelProxy': {'enabled': bool}, 'tunnel': {'enabled': bool},
               'network': {'trustMode': str, 'trustModeOrigin': str},
               'pairing': {'acceptLanRequests': bool}}
    lists = ('trustedNetworks', 'allowedHosts')
    if not isinstance(policy, dict) or set(policy) - (set(scalars) | set(objects) | set(lists)):
        raise ValueError('Unexpected Dashboard source policy fields')
    for field, expected in scalars.items():
        if field in policy:
            if type(policy[field]) is not expected or (field == 'maxConcurrentSubagents' and policy[field] < 0) \
                    or (field == 'spawnRegisterTimeoutMs' and not 5000 <= policy[field] <= 120000):
                raise ValueError(f'Invalid Dashboard source policy field: {field}')
            config[field] = policy[field]
    for field, fields in objects.items():
        if field not in policy:
            continue
        managed = policy[field]
        if not isinstance(managed, dict) or set(managed) - set(fields):
            raise ValueError(f'Unexpected Dashboard source policy fields: {field}')
        for key, expected in fields.items():
            if key in managed and type(managed[key]) is not expected:
                raise ValueError(f'Invalid Dashboard source policy field: {field}.{key}')
        object_field(config, field).update(managed)
    for field in lists:
        if field not in policy:
            continue
        required = policy[field]
        existing = config.setdefault(field, [])
        if any(not isinstance(items, list) or not all(isinstance(item, str) for item in items)
               for items in (required, existing)):
            raise ValueError(f'Expected {field} to be a string list')
        for value in required:
            if value not in existing:
                existing.append(value)


def configure(core, home, bind_host=None):
    validate_build(core)
    current = home / '.local/share/pi-dashboard/current'
    if not shutil.which('tmux'):
        raise ValueError('Dashboard requires tmux for interactive sandbox sessions')
    directory = home / '.pi/dashboard'
    config_path = directory / 'config.json'
    overrides_path = directory / 'tool-overrides.json'
    # Validate all inputs before publishing any state or bridge link.
    config = read_object(config_path)
    overrides = read_object(overrides_path)
    settings = home / '.pi/agent/settings.json'
    if not settings.exists():
        raise ValueError('Run ./setup dotfiles first to install the declarative Dashboard bridge registration')
    # Pi settings remain Dotbot-owned (including their symlink). Parse only;
    # never "repair" malformed settings by replacing the tracked source.
    pi_settings = json.loads(settings.read_text())
    if not isinstance(pi_settings, dict):
        raise ValueError(f'Expected a JSON object: {settings}')
    packages = pi_settings.get('packages', [])
    if not isinstance(packages, list) or not any(
            item == './pi-dashboard' or (isinstance(item, dict) and item.get('source') == './pi-dashboard'
                                        and item.get('autoload') is not False and 'extensions' not in item)
            for item in packages):
        raise ValueError('Run ./setup dotfiles first: Pi settings must declaratively register ./pi-dashboard')
    if overrides.get('version', 1) != 1:
        raise ValueError('Unsupported Dashboard tool-overrides version')
    apply_policy(config)
    # Resolve the primary listener here. Optional native loopback is a separate
    # policy switch, never a fallback when Tailscale is unavailable.
    config['bindHost'] = tailnet_ipv4(bind_host) if bind_host is not None else tailscale_address()
    overrides['version'] = 1
    pi = object_field(object_field(overrides, 'overrides'), 'pi')
    pi['path'] = str(ROOT / 'bin/pi')
    link = home / '.pi/agent/pi-dashboard'
    if link.exists() and not link.is_symlink():
        raise ValueError(f'Refusing to replace an existing Pi package: {link}')
    check_link(current)
    check_link(home / '.local/bin/pi-dashboard')
    publish(config_path, (json.dumps(config, indent=2) + '\n').encode())
    publish(overrides_path, (json.dumps(overrides, indent=2) + '\n').encode())
    activate(core, home)
    publish_symlink(link, current)


def setup(checkout=None, install_only=False):
    # Resolve configured tools even before the caller activates a new shell.
    directories = [str(Path(command('mise', 'which', tool)).parent) for tool in ('node', 'pnpm')]
    os.environ['PATH'] = os.pathsep.join([*directories, os.environ['PATH']])
    home = Path.home()
    core = build_source(checkout, home)
    if install_only:
        activate(core, home)
    else:
        configure(core, home)
    print(f'Dashboard source: {core}')
    print('Stop Dashboard, start it again, and reload Pi to use the selected build.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, help='copy current checkout files, then apply the normal patches')
    parser.add_argument('--install-only', action='store_true', help='build and select without configuring policy or enabling the bridge')
    arguments = parser.parse_args()
    try:
        setup(arguments.checkout, arguments.install_only)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        detail = error.stderr or error.stdout if isinstance(error, subprocess.CalledProcessError) else ''
        print(f'Dashboard setup failed: {error}\n{detail}'.rstrip(), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
