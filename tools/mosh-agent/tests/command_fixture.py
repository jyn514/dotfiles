#!/usr/bin/env python3
"""Disposable command fixtures for wrapper process-lifecycle tests."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

name = Path(sys.argv[0]).name
directory = Path(os.environ['FIXTURE_DIR'])


def record(event):
    with (directory / 'events').open('a') as output:
        output.write(json.dumps([name, event, os.getpid(), sys.argv[1:]]) + '\n')


if name == 'ssh-add':
    (directory / 'checked-agent').write_text(os.environ.get('SSH_AUTH_SOCK', ''))
    sys.exit(int(os.environ.get('AGENT_STATUS', '0')))

remote_environment = dict(os.environ, HOME=str(directory / 'remote home'))
if name == 'ssh' and len(sys.argv) > 1:
    if sys.argv[1] == '-G':
        print('identityagent ' + os.environ.get('IDENTITY_AGENT', 'SSH_AUTH_SOCK'))
        sys.exit(int(os.environ.get('SSH_CONFIG_STATUS', '0')))
    if os.environ.get('SSH_DISCOVERY_STATUS'):
        sys.exit(int(os.environ['SSH_DISCOVERY_STATUS']))
    sys.exit(subprocess.run(['/bin/sh', '-c', sys.argv[-1]], env=remote_environment).returncode)
if name == 'native-ssh':
    sys.exit(subprocess.run(['/bin/sh', '-c', sys.argv[-1]], env=remote_environment).returncode)
if name == 'mosh-server':
    (directory / 'remote-agent').write_text(os.environ.get('SSH_AUTH_SOCK', ''))
    (directory / 'remote-command').write_text(json.dumps(
        sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
    print('MOSH CONNECT 60000 AAAAAAAAAAAAAAAAAAAAAA')
    sys.exit(0)
if name == 'native-client':
    sys.exit(0)
if name == 'mosh' and os.environ.get('NATIVE_MOSH'):
    sys.exit(subprocess.run([os.environ['NATIVE_MOSH'], '--no-init', '--no-ssh-pty',
        '--family=inet', '--experimental-remote-ip=local',
        '--ssh=' + str(directory / 'native-ssh'),
        '--client=' + str(directory / 'native-client'), *sys.argv[1:]]).returncode)

# Record descriptor ownership before opening fixture files: FD 3 is the
# wrapper's saved stdin, and must not survive into either child's process.
try:
    os.fstat(3)
    saved_stdin_open = True
except OSError:
    saved_stdin_open = False
stdin = os.fstat(0)
null = os.stat(os.devnull)
(directory / f'{name}-descriptors').write_text(json.dumps({
    'saved_stdin_open': saved_stdin_open,
    'stdin_is_devnull': (stdin.st_dev, stdin.st_ino) == (null.st_dev, null.st_ino),
}))

child = None


def stop(signum, _frame):
    if child is not None:
        child.terminate()
        child.wait(timeout=5)
    record('stopped')
    sys.exit(128 + signum)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGHUP, stop)
if name == 'autossh':
    child = subprocess.Popen([str(directory / 'ssh')])
    deadline = time.monotonic() + 5
    while not (directory / 'events').exists() or '"ssh", "started"' not in (directory / 'events').read_text():
        if time.monotonic() > deadline:
            child.terminate()
            child.wait()
            sys.exit(99)
        time.sleep(0.01)
record('started')
if name == 'mosh':
    # Do not finish before the tunnel supervisor has entered its signal handler.
    deadline = time.monotonic() + 5
    while not (directory / 'events').exists() or 'autossh' not in (directory / 'events').read_text():
        if time.monotonic() > deadline:
            sys.exit(99)
        time.sleep(0.01)
    print(sys.stdin.readline().strip(), flush=True)
    if os.environ.get('MOSH_WAIT') != '1':
        sys.exit(int(os.environ.get('MOSH_STATUS', '0')))
while True:
    time.sleep(0.05)
