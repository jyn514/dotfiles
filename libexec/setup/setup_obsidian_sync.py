#!/usr/bin/env python3
"""Configure Obsidian's headless client and its native user services."""

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


VAULT_NAME = 'notes'
VAULT_DIRECTORY = Path('Documents/notes')


def command(*args, capture=False):
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def systemd_argument(value):
    # ExecStart uses systemd quoting, specifiers, and environment expansion.
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace(
        '%', '%%').replace('$', '$$').replace('\n', '\\n').replace('\r', '\\r') + '"'


def service_name(vault):
    # Remote IDs are opaque: encode them rather than treating them as paths.
    return 'obsidian-sync-' + vault['id'].encode().hex()


def service_file(platform, vault, executable, home, node_directory):
    name = service_name(vault)
    arguments = [*executable, 'sync', '--continuous', '--path', vault['path']]
    if platform == 'linux':
        contents = (
            '[Unit]\nDescription=Obsidian headless sync\n\n'
            '[Service]\nType=simple\n'
            'Environment="PATH=' + node_directory.replace('%', '%%').replace('"', '\\"') + ':/usr/bin:/bin"\n'
            'ExecStart=' + ' '.join(map(systemd_argument, arguments)) + '\n'
            'Restart=on-failure\nRestartSec=10\nUMask=0077\n\n'
            '[Install]\nWantedBy=default.target\n'
        ).encode()
        return home / '.config/systemd/user' / (name + '.service'), contents
    logs = home / 'Library/Logs'
    return home / 'Library/LaunchAgents' / (name + '.plist'), plistlib.dumps({
        'Label': name,
        'ProgramArguments': arguments,
        'EnvironmentVariables': {'PATH': node_directory + ':/usr/bin:/bin'},
        'RunAtLoad': True,
        'KeepAlive': {'SuccessfulExit': False},
        'ThrottleInterval': 10,
        'Umask': 0o077,
        'StandardOutPath': str(logs / (name + '.log')),
        'StandardErrorPath': str(logs / (name + '.log')),
    })


def publish(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def gui_plugins(path):
    if not path.exists():
        return []  # Sync is opt-in; an unconfigured GUI has it disabled.
    plugins = json.loads(path.read_text())
    if isinstance(plugins, list) and all(isinstance(item, str) for item in plugins):
        return plugins
    if isinstance(plugins, dict) and all(isinstance(item, bool) for item in plugins.values()):
        return plugins
    raise ValueError(f'Unrecognized Obsidian plugin configuration: {path}')


class GuiLauncher:
    """Bind the GUI installation on first use, for one setup transaction."""

    def __init__(self):
        self.executable = None
        self.flatpak = False

    def __call__(self, vault, *args):
        if self.executable is None:
            cli = shutil.which('obsidian')
            if cli:
                self.executable = cli
            else:
                flatpak = shutil.which('flatpak')
                installed = flatpak and subprocess.run(
                    [flatpak, 'info', 'md.obsidian.Obsidian'], capture_output=True,
                ).returncode == 0
                if not installed:
                    raise RuntimeError('Close Obsidian and rerun setup to disable GUI Sync')
                self.executable = flatpak
                self.flatpak = True
        launcher = [self.executable]
        if self.flatpak:
            launcher += ['run', '--cwd=' + vault['path'], 'md.obsidian.Obsidian']
        result = subprocess.run([*launcher, *args], cwd=vault['path'],
                                text=True, capture_output=True, timeout=20)
        # Obsidian can report a disabled CLI while returning success.
        if 'command line interface is not enabled' in (result.stdout + result.stderr).lower():
            raise RuntimeError('Enable Command line interface in Obsidian Settings > General > Advanced, '
                               'or close Obsidian and rerun setup')
        result.check_returncode()
        return result


def preflight_gui(vault, gui):
    running = subprocess.run(['pgrep', '-u', str(os.getuid()), '-ix', 'obsidian'],
                             capture_output=True)
    if running.returncode not in (0, 1):
        raise RuntimeError('Could not determine whether Obsidian is running')
    if running.returncode == 0:
        # The CLI selects the vault from cwd. Verify that selection before mutation.
        result = gui(vault, 'vault', 'info=path')
        if Path(result.stdout.strip()).resolve() != Path(vault['path']).resolve():
            raise RuntimeError('Obsidian CLI selected another vault; close Obsidian and rerun setup')
    return running.returncode == 0


def disable_gui_sync(vault, executable, gui):
    # Recheck immediately before mutation: the app may have opened during login.
    running = preflight_gui(vault, gui)
    status = json.loads(command(*executable, 'sync-status', '--path', vault['path'],
                                '--json', capture=True).stdout)
    # Keep the local GUI choice from propagating to phones or being overwritten.
    configs = status['configs']
    path = Path(vault['path']) / status['configDir'] / 'core-plugins.json'
    if 'core-plugin' in configs:
        command(*executable, 'sync-config', '--path', vault['path'], '--configs',
                ','.join(item for item in configs if item != 'core-plugin'))
    if running:
        gui(vault, 'plugin:disable', 'id=sync', 'filter=core')
        enabled = gui(vault, 'plugins:enabled', 'filter=core')
        plugins = gui_plugins(path)
        persisted = plugins.get('sync', False) if isinstance(plugins, dict) else 'sync' in plugins
        if persisted or 'sync' in enabled.stdout.splitlines():
            raise RuntimeError('GUI Sync is still enabled; close Obsidian and rerun setup')
    else:
        plugins = gui_plugins(path)
        if isinstance(plugins, list):
            plugins = [item for item in plugins if item != 'sync']
        else:
            plugins['sync'] = False
        publish(path, (json.dumps(plugins, indent=2) + '\n').encode())


def configure(executable, gui):
    result = command(*executable, 'sync-list-local', '--json', capture=True)
    vaults = json.loads(result.stdout)['vaults']
    if not vaults:
        if not sys.stdin.isatty():
            raise RuntimeError('No headless vault configured; rerun ./setup services interactively')
        path = str(Path.home() / VAULT_DIRECTORY)
        preflight_gui({'path': path}, gui)
        print('Headless Sync will replace GUI Sync on this machine. Back up your notes first.')
        command(*executable, 'login')
        print(f'Connecting remote vault {VAULT_NAME!r} to {path}')
        command(*executable, 'sync-setup', '--vault', VAULT_NAME, '--path', path)
        result = command(*executable, 'sync-list-local', '--json', capture=True)
        vaults = json.loads(result.stdout)['vaults']
    for vault in vaults:
        command(*executable, 'sync-status', '--path', vault['path'])
    return vaults


def setup():
    if sys.platform not in ('linux', 'darwin'):
        raise RuntimeError('Headless Sync services support Linux and macOS')
    mise = shutil.which('mise')
    if not mise:
        raise RuntimeError('Install mise and Node with ./setup local first')
    command(mise, 'install', '--yes', 'npm:obsidian-headless')
    # Explicit Node avoids relying on the service manager's minimal PATH.
    node = command(mise, 'which', 'node', capture=True).stdout.strip()
    executable = [command(mise, 'which', 'ob', capture=True).stdout.strip()]
    node_directory = str(Path(node).parent)
    os.environ['PATH'] = node_directory + os.pathsep + os.environ['PATH']
    gui = GuiLauncher()
    vaults = configure(executable, gui)
    home = Path.home()
    for vault in vaults:
        disable_gui_sync(vault, executable, gui)
        path, contents = service_file(sys.platform, vault, executable, home, node_directory)
        publish(path, contents)
        if sys.platform == 'linux':
            command('systemctl', '--user', 'daemon-reload')
            command('systemctl', '--user', 'enable', path.name)
            command('systemctl', '--user', 'restart', path.name)
            command('systemctl', '--user', 'is-active', path.name)
        else:
            (home / 'Library/Logs').mkdir(parents=True, exist_ok=True)
            target = f'gui/{os.getuid()}'
            service = target + '/' + service_name(vault)
            command('plutil', '-lint', str(path))
            command('launchctl', 'enable', service)
            loaded = subprocess.run(['launchctl', 'print', service], capture_output=True)
            if loaded.returncode == 0:
                command('launchctl', 'bootout', service)
            command('launchctl', 'bootstrap', target, str(path))
            command('launchctl', 'print', service)
        print(f'Headless Sync service configured for {vault["path"]}: {path}')


if __name__ == '__main__':
    try:
        setup()
    except (OSError, ValueError, RuntimeError, EOFError, subprocess.SubprocessError) as error:
        print(f'obsidian-sync setup failed: {error}', file=sys.stderr)
        raise SystemExit(1)
