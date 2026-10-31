#!/usr/bin/env python3
"""Apply Dashboard's reviewed patch inside mise, then reconcile local policy.

Only the postinstall entry point changes installed package files. Configuration
never starts the daemon or rewrites Pi's symlinked settings.
"""

import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TOOL = 'npm:@blackbelt-technology/pi-agent-dashboard'
PACKAGE = TOOL.removeprefix('npm:')
STAMP = '.dotfiles-dashboard-patch.json'
EXTENSION_ALIAS = '.dotfiles-dashboard-extension'
POLICY = ROOT / 'config/pi-dashboard.json'


def command(*args, env=None):
    return subprocess.run(args, check=True, text=True, capture_output=True, env=env).stdout.strip()


def pin():
    # Let the existing owning tool parse TOML; do not require a newer global
    # Python just for tomllib (bootstrap Python is intentionally task-scoped).
    # mise 2026.9.18 splits dotted paths literally: quoting the tool key makes
    # the quotes part of the key. This tool name contains no dots.
    version = command('mise', 'config', 'get', '--file', str(ROOT / 'config/mise.toml'),
                      f'tools.{TOOL}.version')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError(f'{TOOL} must pin an exact X.Y.Z release in config/mise.toml')
    return version


def patch_file(version):
    return ROOT / 'libexec/setup/patches' / f'pi-dashboard-{version}.patch'


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


def publish_symlink(path, target):
    if path.exists() and not path.is_symlink():
        raise ValueError(f'Refusing to replace an existing path: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
        replacement = Path(temporary) / path.name
        replacement.symlink_to(target, target_is_directory=True)
        replacement.replace(path)


def installed_core(install):
    # Ask pnpm for its actual global dependency, not a guessed version/store
    # directory. The environment form also works with pnpm 12's Rust CLI.
    env = os.environ | {
        'PNPM_CONFIG_GLOBAL_DIR': str(install),
        'PNPM_CONFIG_GLOBAL_BIN_DIR': str(install / 'bin'),
        'PATH': str(install / 'bin') + os.pathsep + os.environ['PATH'],
    }
    records = json.loads(command('pnpm', 'list', '--global', '--depth=0', '--json', env=env))
    matches = [Path(record['dependencies'][PACKAGE]['path']).resolve()
               for record in records if PACKAGE in record.get('dependencies', {})]
    if len(matches) != 1:
        raise ValueError('pnpm did not identify exactly one Dashboard core package')
    core = matches[0]
    if not core.is_relative_to(install.resolve()):
        raise ValueError('Dashboard resolves outside its owning mise installation')
    return core


def component_roots(core):
    # Module lookup paths bypass restrictive package exports without guessing
    # pnpm's store layout. Walk component dependencies too: shared is transitive.
    result = command('node', str(ROOT / 'libexec/setup/setup_dashboard_roots.mjs'), str(core))
    return {name: [Path(path) for path in paths] for name, paths in json.loads(result).items()}


def validate_roots(core, components, version, install):
    expected = {core: PACKAGE}
    for component, roots in components.items():
        if not roots:
            raise ValueError(f'Missing Dashboard {component} package')
        expected.update({root: f'@blackbelt-technology/pi-dashboard-{component}' for root in roots})
    for root, name in expected.items():
        metadata = json.loads((root / 'package.json').read_text())
        if metadata.get('name') != name or metadata.get('version') != version:
            raise ValueError(f'Dashboard version/name mismatch at {root}: expected {name}@{version}')
        if not root.resolve().is_relative_to(install.resolve()):
            raise ValueError(f'Dashboard component outside owning installation: {root}')
    for root in components['extension']:
        extensions = json.loads((root / 'package.json').read_text()).get('pi', {}).get('extensions', [])
        if 'src/bridge.ts' not in extensions or not (root / 'src/bridge.ts').is_file():
            raise ValueError(f'Dashboard runtime extension does not publicly expose its bridge: {root}')
    if not (core / 'packages/extension/src/bridge.ts').is_file():
        raise ValueError('Dashboard bundled bridge is missing')
    for root in components['web']:
        if not (root / 'dist/index.html').is_file():
            raise ValueError('Dashboard browser distribution is missing')


def runtime_extension(core, components):
    extension = Path(command('node', str(ROOT / 'libexec/setup/setup_dashboard_roots.mjs'),
                             str(core), '--extension'))
    if extension not in components['extension']:
        raise ValueError('Dashboard runtime extension is outside the validated package graph')
    return extension


def files(directory):
    return {path.relative_to(directory): path.read_bytes()
            for path in directory.rglob('*') if path.is_file()}


def native_patch(stage, patch, reverse=False):
    args = ['patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '--reject-file=-',
            '-p1', '-d', str(stage), '-i', str(patch)]
    args.append('--reverse' if reverse else '--forward')
    # Dry-run first: a failed hunk must never leave a partially patched install.
    command(*args, '--dry-run')
    command(*args)


def destinations(relative, core, components):
    parts = relative.parts
    if len(parts) < 3 or parts[0] != 'packages':
        raise ValueError(f'Patch changed an unsupported path: {relative}')
    component = parts[1]
    if component == 'client' and len(parts) > 3 and parts[2] == 'dist':
        return [root / 'dist' / Path(*parts[3:]) for root in components['web']]
    if component not in ('server', 'shared', 'extension') or parts[2] != 'src':
        raise ValueError(f'Patch changed an unsupported source path: {relative}')
    return [core / relative, *(root / Path(*parts[2:]) for root in components[component])]


def postinstall():
    version = pin()
    if os.environ.get('MISE_TOOL_VERSION') != version or not os.environ.get('MISE_TOOL_INSTALL_PATH'):
        raise ValueError('Dashboard patch must run as the matching mise postinstall hook')
    install = Path(os.environ['MISE_TOOL_INSTALL_PATH']).resolve()
    patch = patch_file(version)
    patch_bytes = patch.read_bytes()  # Missing versioned patch fails closed.
    core = installed_core(install)
    components = component_roots(core)
    validate_roots(core, components, version, install)
    extension = runtime_extension(core, components)
    state_file = install / STAMP
    previous = json.loads(state_file.read_text()) if state_file.exists() else None
    if previous:
        if previous.get('version') != version:
            raise ValueError('Dashboard patch receipt has a different upstream version')
        for path, expected in previous['files'].items():
            target = install / path
            actual = digest(target.read_bytes()) if target.exists() else None
            if actual != expected:
                raise ValueError(f'Installed Dashboard drifted since patching: {target}')
        if previous['patch_sha256'] == digest(patch_bytes):
            publish_symlink(install / EXTENSION_ALIAS, extension)
            return
    # Work on copies, never pnpm's hard-linked content-addressable store files.
    # Core source and resolved split components both execute in this release.
    with tempfile.TemporaryDirectory(prefix='dashboard-patch-') as temporary:
        stage = Path(temporary) / 'stage'
        shutil.copytree(core, stage, ignore=shutil.ignore_patterns('node_modules'))
        shutil.copytree(components['web'][0] / 'dist', stage / 'packages/client/dist')
        before = files(stage)
        if previous:
            old = Path(temporary) / 'previous.patch'
            old.write_text(previous['patch'])
            native_patch(stage, old, reverse=True)
        pristine = files(stage)
        # Apply exactly the bytes named by the receipt even if the checkout's
        # patch is regenerated while this installation hook is running.
        selected_patch = Path(temporary) / 'reviewed.patch'
        selected_patch.write_bytes(patch_bytes)
        native_patch(stage, selected_patch)
        after = files(stage)
        # Match upstream precompress.mjs: compressible assets and index.html
        # at least 1 KiB, best gzip compression. Also refresh existing sidecars
        # if a changed source shrinks, and remove generated sidecars whose
        # source was removed when reversing an older patch.
        compressible = {'.js', '.css', '.html', '.svg', '.json', '.map', '.txt'}
        for path in before.keys() | after.keys():
            if path.parts[:3] != ('packages', 'client', 'dist'):
                continue
            contents = after.get(path)
            compressed = Path(str(path) + '.gz')
            if contents is None:
                (stage / compressed).unlink(missing_ok=True)
            elif pristine.get(path) != contents or before.get(path) != contents:
                eligible = path.parts[3] == 'assets' or path.name == 'index.html'
                if compressed in before or (eligible and path.suffix in compressible and len(contents) >= 1024):
                    (stage / compressed).write_bytes(gzip.compress(contents, compresslevel=9, mtime=0))
        after = files(stage)
        changed = {path for path in pristine.keys() | after.keys()
                   if pristine.get(path) != after.get(path)}
        # Include restored files when the reviewed patch changes or shrinks.
        changed |= {path for path in before.keys() | after.keys()
                    if before.get(path) != after.get(path)}
        updates = {}
        for path in sorted(changed):
            for target in destinations(path, core, components):
                actual = target.read_bytes() if target.exists() else None
                if actual != before.get(path):
                    raise ValueError(f'Dashboard component differs from canonical source: {target}')
                updates[target] = after.get(path)
        receipt = {}
        for target, contents in updates.items():
            if contents is None:
                target.unlink(missing_ok=True)
            else:
                publish(target, contents, target.stat().st_mode & 0o777 if target.exists() else 0o644)
            receipt[str(target.relative_to(install))] = digest(contents) if contents is not None else None
        publish(state_file, (json.dumps({
            'version': version, 'patch_sha256': digest(patch_bytes),
            'packages': json.loads(command('node', str(ROOT / 'libexec/setup/setup_dashboard_roots.mjs'),
                                           str(core), '--versions')),
            'patch': patch_bytes.decode(), 'files': receipt,
        }, indent=2) + '\n').encode())
        publish_symlink(install / EXTENSION_ALIAS, extension)


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


def configure(core, install, home, bind_host=None):
    version = pin()
    components = component_roots(core)
    validate_roots(core, components, version, install)
    # The split package owns the bridge's runtime dependencies. The bundled
    # core sources are still patched for native CLI use, but are not loadable
    # as a Pi package without unpublished development dependencies.
    extension = runtime_extension(core, components)
    extension_alias = install / EXTENSION_ALIAS
    receipt = json.loads((install / STAMP).read_text())
    if receipt.get('version') != version or receipt.get('patch_sha256') != digest(patch_file(version).read_bytes()):
        raise ValueError('Dashboard patch changed; reinstall the mise tool before configuring')
    for path, expected in receipt['files'].items():
        target = install / path
        if (digest(target.read_bytes()) if target.exists() else None) != expected:
            raise ValueError(f'Installed Dashboard patch is not intact: {target}')
    if not extension_alias.is_symlink() or extension_alias.resolve() != extension:
        publish_symlink(extension_alias, extension)
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
    publish(config_path, (json.dumps(config, indent=2) + '\n').encode())
    publish(overrides_path, (json.dumps(overrides, indent=2) + '\n').encode())
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.is_symlink() or link.resolve() != extension:
        publish_symlink(link, extension_alias)


def setup():
    # mise owns installation and patch application. Never repair package source
    # here: a stale/failed patch must stop before exposing the bridge to Pi.
    # `config_source` can resolve through the active global-config symlink even
    # when this helper belongs to an isolated worktree. Carry the actual owner
    # into the hook instead of letting mise select another checkout.
    hook_env = os.environ | {'DOTFILES_DASHBOARD_ROOT': str(ROOT)}
    command('mise', 'install', '--yes', TOOL, env=hook_env)
    install = Path(command('mise', 'where', TOOL)).resolve()
    # A fresh shell may not have activated mise yet. Resolve the installed
    # dependencies through their owner rather than requiring a shell reload.
    directories = [str(Path(command('mise', 'which', tool)).parent) for tool in ('node', 'pnpm')]
    os.environ['PATH'] = os.pathsep.join([*directories, os.environ['PATH']])
    configure(installed_core(install), install, Path.home())


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['postinstall']:
            postinstall()
        elif not sys.argv[1:]:
            setup()
        else:
            raise ValueError('usage: setup_dashboard.py [postinstall]')
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Dashboard setup failed: {error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            for output in (error.stdout, error.stderr):
                if output:
                    print(output, file=sys.stderr, end='' if output.endswith('\n') else '\n')
        raise SystemExit(1)
