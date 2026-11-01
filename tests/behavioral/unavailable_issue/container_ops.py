"""Filesystem operations inside the disposable Flower worker, never on the host."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys


ROOT = Path('/workspace/flower')
ISSUE = Path('/task/issue.md')


def inventory():
    result = {}
    for base, dirs, files in os.walk(ROOT, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(base) / name
            info = path.lstat()
            relative = path.relative_to(ROOT).as_posix()
            if stat.S_ISLNK(info.st_mode):
                result[relative] = {'symlink': os.readlink(path)}
            elif stat.S_ISREG(info.st_mode):
                result[relative] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                    'mode': stat.S_IMODE(info.st_mode)}
    return result


def shell(data):
    child = subprocess.Popen(['bash', '-c', data['command']], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = child.communicate(timeout=data['timeout'])
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        output, _ = child.communicate()
    code = child.returncode if child.returncode >= 0 else 128 - child.returncode
    return {'exit_code': code, 'output': output.decode('utf-8', errors='replace')}


def operation(action, args):
    if action == 'task':
        data = json.load(sys.stdin)
        ISSUE.write_text(data['issue'])
        ISSUE.chmod(0o000 if data['mode'] == 'unreadable' else 0o444)
        packet = Path('/task/packet.md')
        packet.write_text(data['packet'])
        packet.chmod(0o444)
    elif action == 'historical':
        data = json.load(sys.stdin)
        # Resolve the real binaries before creating the substitutes.
        executables = {name: shutil.which(name) for name in ['bb', 'git']}
        if not all(executables.values()):
            raise FileNotFoundError('Historical worker requires native bb and git')
        Path('/task/commands.json').write_text(json.dumps({**data, 'executables': executables}))
        directory = Path('/task/bin')
        directory.mkdir()
        Path('/task/historical_commands.py').chmod(0o755)
        for name in executables:
            (directory / name).symlink_to('/task/historical_commands.py')
    elif action == 'historical-worker':
        data = json.load(sys.stdin)
        Path('/tmp/worker-home').mkdir(mode=0o755)
        protected = ROOT / 'target/flower-worker'
        protected.mkdir(parents=True, exist_ok=True)
        (protected / 'packet.md').write_text(data['packet'])
        if data.get('repository', True):
            with (ROOT / '.git/info/exclude').open('a') as exclude:
                exclude.write('\ntarget/flower-worker/\n')
    elif action == 'read':
        return base64.b64encode(Path(args[0]).read_bytes()).decode('ascii')
    elif action == 'write':
        Path(args[0]).write_bytes(sys.stdin.buffer.read())
    elif action == 'chmod':
        Path(args[0]).chmod(int(args[1], 8))
    elif action == 'unlink':
        Path(args[0]).unlink()
    elif action == 'mkdir':
        Path(args[0]).mkdir(parents=True, exist_ok=True)
    elif action == 'access':
        with open(args[0], 'r+b' if args[1] == 'rw' else 'rb'):
            pass
    elif action == 'inventory':
        return inventory()
    elif action == 'shell':
        return shell(json.load(sys.stdin))
    elif action == 'permissions':
        info = ISSUE.stat()
        return {'uid': os.getuid(), 'issue_uid': info.st_uid,
                'mode': stat.S_IMODE(info.st_mode),
                'task_directory_uid': ISSUE.parent.stat().st_uid}
    else:
        raise ValueError(f'Unknown operation: {action}')


if __name__ == '__main__':
    try:
        value = operation(sys.argv[1], sys.argv[2:])
        print(json.dumps({'ok': True, 'value': value}))
    except OSError as error:
        # Expected worker-side errors travel in a successful transport envelope.
        # Docker/relay failures cannot masquerade as ordinary tool exit codes.
        print(json.dumps({'ok': False, 'error_type': type(error).__name__, 'error': str(error)}))
