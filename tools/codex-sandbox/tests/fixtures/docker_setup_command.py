#!/usr/bin/env python3
"""Disposable installer/systemctl commands for Docker setup output tests."""

import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
action = 'install' if command == 'dockerd-rootless-setuptool.sh' else sys.argv[2]
with Path(os.environ['SETUP_COMMANDS']).open('a') as receipt:
    receipt.write(json.dumps([command, *sys.argv[1:]]) + '\n')
if os.environ.get('SETUP_FAIL') == action:
    print(f'current {action} failure', file=sys.stderr)
    raise SystemExit(7)
if action == 'install':
    print('old daemon: healthcheck failed fatally')
    print('old unit: Run daemon-reload', file=sys.stderr)
elif action == 'show':
    state = {'ActiveState': 'active', 'SubState': 'running', 'Result': 'success',
             'ExecMainStatus': '0', 'NeedDaemonReload': 'no', 'MainPID': '4242',
             'ExecMainStartTimestamp': 'Tue 2026-10-13 08:42:47 EDT'}
    state.update(json.loads(os.environ.get('SETUP_STATE', '{}')))
    for key, value in state.items():
        print(f'{key}={value}')
