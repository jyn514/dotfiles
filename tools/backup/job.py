#!/usr/bin/env python3
"""Root-owned scheduled capture; repository credentials are used only as restic."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys


CONFIG = Path('/etc/dotfiles-backup.json')
STATE = Path('/var/lib/dotfiles-backup')


def progress(message):
    print(f'backup: {message}', file=sys.stderr, flush=True)


def run_as(user, arguments, *, environment=None, capture=False, timeout=None):
    account = pwd.getpwnam(user)
    if os.getuid() not in (0, account.pw_uid):
        raise PermissionError(f'cannot run as {user} without root')
    env = {'HOME': account.pw_dir, 'USER': user, 'LOGNAME': user,
           'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    env.update(environment or {})

    def drop_privileges():
        os.initgroups(user, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)

    return subprocess.run(arguments, env=env, cwd='/', check=True,
                          preexec_fn=drop_privileges if os.getuid() == 0 else None,
                          capture_output=capture, text=True, timeout=timeout)


class Job:
    def __init__(self, config, state=STATE):
        self.config = config
        self.state = Path(state)
        self.marker = self.state / 'mica-stopped.json'

    def docker(self, *arguments, capture=False):
        mica = self.config['mica']
        return run_as(self.config['owner'],
                      [mica['docker'], '--host', 'unix://' + mica['socket'], *arguments],
                      capture=capture, timeout=90)

    def verify_engine(self):
        actual = self.docker('info', '--format', '{{.ID}}', capture=True).stdout.strip()
        if actual != self.config['mica']['engine']:
            raise RuntimeError('Docker engine changed; rerun setup backup before capturing Mica')

    def inspect(self, identity):
        return json.loads(self.docker('inspect', identity, capture=True).stdout)[0]

    def recover(self):
        if not self.marker.exists():
            return
        self.verify_engine()
        identity = json.loads(self.marker.read_text())['container']
        progress('restarting Mica from the interrupted capture')
        self.docker('start', identity)
        if not self.inspect(identity)['State']['Running']:
            raise RuntimeError('Mica did not restart; recovery marker retained')
        self.marker.unlink()

    def capture(self):
        mica = self.config['mica']
        self.verify_engine()
        container = self.inspect(mica['container'])
        mounts = [m for m in container['Mounts'] if m['Destination'] == '/state']
        if (len(mounts) != 1 or mounts[0]['Type'] != 'bind'
                or mounts[0]['Source'] != mica['source']):
            raise RuntimeError('Mica /state mount changed; rerun setup backup')
        identity = container['Id']
        destination = self.state / 'mica-state'
        private = self.state / 'capture-private'
        private.mkdir(mode=0o700, exist_ok=True)
        temporary = private / 'mica-state'
        # An incomplete copy is never uploaded. Keep the previous complete copy
        # until this capture has completed and Mica has restarted.
        if temporary.exists():
            shutil.rmtree(temporary)
        try:
            if container['State']['Running']:
                self.marker.write_text(json.dumps({'container': identity}) + '\n')
                with self.marker.open('rb') as marker:
                    os.fsync(marker.fileno())
                progress('stopping Mica (60 second shutdown grace)')
                self.docker('stop', '--time', '60', identity)
                stopped = self.inspect(identity)['State']
                if stopped['Running'] or stopped['ExitCode'] == 137:
                    raise RuntimeError('Mica did not stop cleanly; capture rejected')
            progress(f'copying Mica state from {mica["source"]}')
            shutil.copytree(mica['source'], temporary, symlinks=True)
        finally:
            self.recover()
        account = pwd.getpwnam('restic')
        for root, directories, files in os.walk(temporary, followlinks=False):
            os.chown(root, account.pw_uid, account.pw_gid, follow_symlinks=False)
            for name in directories + files:
                os.chown(Path(root) / name, account.pw_uid, account.pw_gid,
                         follow_symlinks=False)
        temporary.chmod(0o700)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.rename(destination)
        return destination

    def upload(self, tag, root=None, *arguments):
        env = {'BACKUP_HOME': self.config['home'],
               'RESTIC_ENV_FILE': self.config['credentials'],
               'RESTIC_BINARY': self.config['restic'],
               'BACKUP_TAG': tag,
               'BACKUP_HOST': self.config['host'],
               'PATH': str(Path(self.config['restic']).parent) + ':/usr/bin:/bin'}
        if root is not None:
            env['BACKUP_ROOT'] = str(root)
        progress(f'{tag}: running restic as restic')
        run_as('restic', ['/bin/sh', str(Path(__file__).parent / 'backup.sh'), *arguments],
               environment=env)

    def daily(self):
        errors = []
        if self.config.get('mica'):
            try:
                self.recover()
                self.upload('mica-state', self.capture())
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                errors.append(f'mica-state: {error}')
        # A failure in one backup does not suppress the other.
        try:
            self.upload('documents-backup')
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            errors.append(f'documents-backup: {error}')
        if errors:
            raise RuntimeError('; '.join(errors))
        progress('daily backups complete')


def interrupted(signum, frame):
    raise RuntimeError(f'interrupted by signal {signum}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['daily', 'recover', 'verify-mica'])
    args = parser.parse_args()
    if os.getuid() != 0:
        parser.error('scheduled capture requires root; use sudo')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    config = json.loads(CONFIG.read_text())
    job = Job(config)
    # Native schedulers serialize their own job; this also covers manual runs.
    with (STATE / 'job.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if args.command != 'daily':
                progress('another backup is running; retry this command after it completes')
                return 1
            progress('another backup is running; skipping this invocation')
            return 0
        try:
            if args.command == 'daily':
                job.daily()
            elif args.command == 'recover':
                job.recover()
            else:
                target = STATE / 'restore-check'
                if target.exists():
                    shutil.rmtree(target)
                target.mkdir(mode=0o700)
                account = pwd.getpwnam('restic')
                os.chown(target, account.pw_uid, account.pw_gid)
                job.upload('mica-state', None, 'restore', 'latest', '--tag', 'mica-state',
                           '--host', config['host'],
                           '--target', str(target))
                saved = STATE / 'mica-state'
                if not saved.is_dir():
                    raise RuntimeError('no staged Mica snapshot to compare')
                compare_trees(saved, target)
                shutil.rmtree(target)
                progress('Mica restore matches the staged snapshot')
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            progress(f'failed: {error}; staged state and recovery marker are retained')
            return 1
    return 0


def compare_trees(source, restored):
    """Compare contents and links, rather than live state that has already changed."""
    import hashlib

    def inventory(root):
        result = {}
        for directory, directories, files in os.walk(root, followlinks=False):
            for name in directories + files:
                path = Path(directory) / name
                relative = str(path.relative_to(root))
                if path.is_symlink():
                    result[relative] = ('link', os.readlink(path))
                elif path.is_dir():
                    result[relative] = ('directory',)
                else:
                    digest = hashlib.sha256()
                    with path.open('rb') as file:
                        for block in iter(lambda: file.read(1024 * 1024), b''):
                            digest.update(block)
                    result[relative] = ('file', digest.hexdigest())
        return result

    if inventory(source) != inventory(restored):
        raise RuntimeError('restored files differ from the staged Mica snapshot')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        progress(f'failed: {error}; inspect scheduler logs and run recovery before retrying')
        raise SystemExit(1)
