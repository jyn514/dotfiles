#!/usr/bin/python3
"""Configure the owned Docker user service before its first start."""

from pathlib import Path
import subprocess
import shutil
import sys


def step(label, arguments, timeout):
    print(f'Docker setup: {label}...', file=sys.stderr, flush=True)
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        print(f'Docker setup: {label} failed (exit {result.returncode}).', file=sys.stderr)
        for output in (result.stdout, result.stderr):
            if output:
                print(output.rstrip(), file=sys.stderr)
    return result


def main():
    home = Path.home()
    dropin = home / '.config/systemd/user/docker.service.d'
    dropin.mkdir(parents=True, exist_ok=True)
    source = Path('/usr/local/share/codex-sandbox')
    shutil.copyfile(source / 'docker-service.conf', dropin / 'sandbox.conf')
    for name in ('sandbox.slice', 'sandbox-reclaim.service', 'sandbox-reclaim.timer',
                 'sandbox-image-gc.service', 'sandbox-image-gc.timer'):
        shutil.copyfile(source / name, dropin.parent / name)
    # Preserve operator enablement on repair. The host enables new installations
    # only after their full provisioning audit succeeds.
    for label, arguments, timeout in (
            ('install rootless service', ['dockerd-rootless-setuptool.sh', 'install'], 240),
            ('reload units', ['systemctl', '--user', 'daemon-reload'], 30)):
        result = step(label, arguments, timeout)
        if result.returncode:
            return result.returncode
    restarted = step('restart Docker', ['systemctl', '--user', 'restart', 'docker'], 240)
    state = step('inspect current Docker state', [
        'systemctl', '--user', 'show', 'docker.service',
        '--property=ActiveState,SubState,Result,ExecMainStatus,NeedDaemonReload,MainPID,ExecMainStartTimestamp',
    ], 30)
    if state.returncode == 0:
        print('Docker current state:\n' + state.stdout.rstrip(), file=sys.stderr)
    if restarted.returncode or state.returncode:
        return restarted.returncode or state.returncode
    values = dict(line.split('=', 1) for line in state.stdout.splitlines())
    if any(values.get(key) != expected for key, expected in (
            ('ActiveState', 'active'), ('SubState', 'running'), ('NeedDaemonReload', 'no'))):
        print('Docker setup: restart did not reach active/running with reloaded units.', file=sys.stderr)
        return 1
    print('Docker setup: restart complete; units reloaded.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
