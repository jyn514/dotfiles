#!/usr/bin/env python3
"""Install the existing backup command with the platform's native scheduler."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import pwd
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

from job import CONFIG, STATE, run_as


SOURCE = Path(__file__).resolve().parent
INSTALL = Path('/Library/dotfiles-backup' if sys.platform == 'darwin'
               else '/usr/local/lib/dotfiles-backup')
PYTHON = '/usr/bin/python3'
LABEL = 'com.jyn.backup'


def command(*args):
    subprocess.run(args, check=True)


def ensure_restic(platform):
    try:
        return pwd.getpwnam('restic')
    except KeyError:
        if platform == 'linux':
            command('useradd', '--system', '--user-group', '--create-home',
                    '--home-dir', '/var/lib/restic', '--shell', '/usr/sbin/nologin', 'restic')
        else:
            # macOS has no useradd; choose a free hidden service UID/GID.
            import grp
            used = {p.pw_uid for p in pwd.getpwall()} | {g.gr_gid for g in grp.getgrall()}
            identity = next(i for i in range(400, 500) if i not in used)
            for kind, values in [('Groups', {'PrimaryGroupID': str(identity)}),
                                 ('Users', {'UniqueID': str(identity),
                                            'PrimaryGroupID': str(identity),
                                            'UserShell': '/usr/bin/false',
                                            'NFSHomeDirectory': '/var/lib/restic',
                                            'IsHidden': '1', 'Password': '*'})]:
                record = f'/{kind}/restic'
                command('/usr/bin/dscl', '.', '-create', record)
                for key, value in values.items():
                    command('/usr/bin/dscl', '.', '-create', record, key, value)
        return pwd.getpwnam('restic')


def configuration(owner, restic, docker, mica, credentials):
    account = pwd.getpwnam(owner)
    home = Path(account.pw_dir)
    if account.pw_uid == 0 or owner == 'restic':
        raise ValueError('backup owner must be the human account, not root or restic')
    result = {'owner': owner, 'home': str(home), 'host': socket.gethostname(),
              'restic': str(Path(restic).resolve()),
              'credentials': str(Path(credentials or home / '.local/config/restic.env').resolve())}
    source = home / '.local/share/mica-agent/agent'
    if mica is True or (mica is None and source.is_dir()):
        if not source.is_dir():
            raise ValueError(f'Mica state directory is missing: {source}')
        if not docker:
            raise ValueError('Docker is required for Mica backups')
        docker_socket = home / '.lima/sandbox-host-docker/sock/docker.sock'
        arguments = [docker, '--host', 'unix://' + str(docker_socket)]
        engine = run_as(owner, [*arguments, 'info', '--format', '{{.ID}}'],
                        capture=True, timeout=30).stdout.strip()
        container = json.loads(run_as(owner, [*arguments, 'inspect', 'mica-mica-1'],
                                      capture=True, timeout=30).stdout)[0]
        mounts = [m for m in container['Mounts'] if m['Destination'] == '/state']
        if (len(mounts) != 1 or mounts[0]['Type'] != 'bind'
                or mounts[0]['Source'] != str(source)):
            raise ValueError('Mica /state is not the expected host state directory')
        result['mica'] = {'source': str(source), 'socket': str(docker_socket),
                          'container': 'mica-mica-1', 'engine': engine,
                          'docker': str(Path(docker).resolve())}
    return result


def artifacts(platform, config):
    files = {'dotfiles-backup.json': json.dumps(config, indent=2) + '\n'}
    if platform == 'linux':
        files['dotfiles-backup.service'] = (SOURCE / 'dotfiles-backup.service.in').read_text().replace(
            '@PYTHON@', PYTHON).replace('@INSTALL@', str(INSTALL))
        files['dotfiles-backup.timer'] = (SOURCE / 'dotfiles-backup.timer').read_text()
    else:
        files[LABEL + '.plist'] = plistlib.dumps({
            'Label': LABEL,
            'ProgramArguments': [PYTHON, '-I', str(INSTALL / 'job.py'), 'daily'],
            'StartCalendarInterval': {'Hour': 12, 'Minute': 0},
            'RunAtLoad': True,
            'Umask': 0o077,
            'StandardOutPath': '/var/log/dotfiles-backup.log',
            'StandardErrorPath': '/var/log/dotfiles-backup.log',
        }).decode()
    return files


def publish(path, contents, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def remove_old_cron(owner):
    crontab = shutil.which('crontab')
    if not crontab:
        return
    current = subprocess.run([crontab, '-u', owner, '-l'], capture_output=True, text=True)
    if current.returncode:
        if 'no crontab' in current.stderr.lower():
            return
        raise RuntimeError(f'could not inspect the old cron schedule: {current.stderr.strip()}')
    old_command = str(SOURCE.parents[1] / 'bin/backup')
    old = '0 12 * * * ' + old_command
    lines = current.stdout.splitlines(keepends=True)
    kept = [line for line in lines if line.strip() != old]
    if kept != lines:
        subprocess.run([crontab, '-u', owner, '-'], input=''.join(kept), text=True, check=True)
        print('backup: removed the old current-user cron entry', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', default=os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name)
    parser.add_argument('--restic', default=shutil.which('restic'))
    parser.add_argument('--docker', default=shutil.which('docker'))
    parser.add_argument('--credentials', type=Path)
    mica = parser.add_mutually_exclusive_group()
    mica.add_argument('--mica', dest='mica', action='store_true')
    mica.add_argument('--no-mica', dest='mica', action='store_false')
    parser.set_defaults(mica=None)
    parser.add_argument('--render', type=Path, help='render configuration without installing or enabling it')
    args = parser.parse_args()
    platform = 'macos' if sys.platform == 'darwin' else 'linux' if sys.platform.startswith('linux') else None
    if platform is None:
        parser.error('only macOS and Linux are supported')
    if not args.restic:
        parser.error('install restic first, or pass --restic /absolute/path')
    if os.getuid() != 0 and args.render is None:
        # Keep binary discovery from the human's PATH before sudo resets it.
        arguments = [PYTHON, str(SOURCE / 'install.py'), '--owner', args.owner,
                     '--restic', args.restic]
        if args.docker:
            arguments += ['--docker', args.docker]
        if args.credentials:
            arguments += ['--credentials', str(args.credentials)]
        if args.mica is not None:
            arguments += ['--mica' if args.mica else '--no-mica']
        elevated = ['sudo', *arguments]
        print('backup: elevated command: ' + shlex.join(elevated), file=sys.stderr, flush=True)
        os.execvp('sudo', elevated)
    config = configuration(args.owner, args.restic, args.docker, args.mica, args.credentials)
    files = artifacts(platform, config)
    if args.render:
        args.render.mkdir(parents=True, exist_ok=True)
        for name, contents in files.items():
            (args.render / name).write_text(contents)
        print(f'backup: rendered {platform} configuration in {args.render}; no schedule changed')
        return 0
    if (STATE / 'mica-stopped.json').exists():
        raise RuntimeError('Mica has a pending restart marker; run the installed job.py recover before updating')
    if platform == 'linux':
        active = subprocess.run(['systemctl', 'is-active', 'dotfiles-backup.service'],
                                capture_output=True, text=True)
        if active.stdout.strip() in ('active', 'activating', 'deactivating'):
            raise RuntimeError('backup is running; install again after it completes')
    else:
        loaded = subprocess.run(['launchctl', 'print', 'system/' + LABEL],
                                capture_output=True, text=True)
        if loaded.returncode == 0 and 'state = running' in loaded.stdout:
            raise RuntimeError('backup is running; install again after it completes')
    interpreter = Path(PYTHON).resolve().stat()
    if interpreter.st_uid != 0 or interpreter.st_mode & 0o022:
        raise ValueError(f'{PYTHON} must be a root-owned system Python')
    account = ensure_restic(platform)
    if account.pw_uid == 0:
        raise ValueError('restic must be an unprivileged service account')
    credentials = Path(config['credentials']).stat()
    if (not stat.S_ISREG(credentials.st_mode) or credentials.st_uid != account.pw_uid
            or credentials.st_mode & 0o077):
        raise ValueError('restic.env must be a private regular file owned by restic; contents were not read')
    run_as('restic', ['/usr/bin/test', '-r', config['credentials']])
    home = Path(account.pw_dir)
    home.mkdir(parents=True, exist_ok=True)
    os.chown(home, account.pw_uid, account.pw_gid)
    home.chmod(0o700)
    STATE.mkdir(parents=True, exist_ok=True)
    STATE.chmod(0o711)
    INSTALL.mkdir(parents=True, exist_ok=True)
    INSTALL.chmod(0o755)
    # These are recurring root entrypoints. A writable ancestor would let its
    # owner replace the installed code between scheduled runs.
    for path in [STATE, INSTALL, *INSTALL.parents]:
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f'root backup path must be root-owned and not writable by others: {path}')
    for name in ['job.py', 'backup.sh']:
        publish(INSTALL / name, (SOURCE / name).read_text())
    publish(CONFIG, files['dotfiles-backup.json'], 0o600)
    if platform == 'linux':
        for name in ['dotfiles-backup.service', 'dotfiles-backup.timer']:
            publish(Path('/etc/systemd/system') / name, files[name])
        command('systemctl', 'daemon-reload')
        command('systemctl', 'enable', '--now', 'dotfiles-backup.timer')
        command('systemctl', 'is-enabled', 'dotfiles-backup.timer')
        command('systemctl', 'is-active', 'dotfiles-backup.timer')
        command('systemctl', 'list-timers', '--all', 'dotfiles-backup.timer', '--no-pager')
    else:
        name = LABEL + '.plist'
        target = Path('/Library/LaunchDaemons') / name
        # An update must not unload a running capture.
        if loaded.returncode == 0:
            command('launchctl', 'bootout', 'system/' + LABEL)
        publish(target, files[name])
        command('plutil', '-lint', str(target))
        command('launchctl', 'enable', 'system/' + LABEL)
        command('launchctl', 'bootstrap', 'system', str(target))
        command('launchctl', 'print', 'system/' + LABEL)
    remove_old_cron(args.owner)
    print('backup: daily noon schedule active; run the first backup and restore check from the README')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'backup setup failed: {error}; inspect scheduler status before retrying', file=sys.stderr)
        raise SystemExit(1)
