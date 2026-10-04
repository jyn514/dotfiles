#!/usr/bin/env python3
"""Disposable Docker protocol fixture; never contacts a real daemon."""
import json
import os
from pathlib import Path
import sys

record = Path(os.environ['DOCKER_FIXTURE'])
state = json.loads(record.read_text())
arguments = sys.argv[3:]
operation = arguments[0]
state.setdefault('calls', []).append(operation)
if operation == 'info':
    print(state['engine'])
elif operation == 'inspect':
    print(json.dumps([{'Id': 'owned-container',
                       'State': {'Running': state['running'], 'ExitCode': state.get('exit', 0)},
                       'Mounts': [{'Type': 'bind', 'Destination': '/state',
                                   'Source': state['source']}]}]))
elif operation == 'stop':
    state['running'] = False
    # Models the final Chronicle flush during shutdown.
    (Path(state['source']) / 'records.log').write_text('flushed before capture\n')
elif operation == 'start':
    state['running'] = True
    # Live state changes again before upload; restore must use the captured copy.
    (Path(state['source']) / 'records.log').write_text('live after restart\n')
else:
    raise SystemExit('unsupported fixture operation: ' + operation)
record.write_text(json.dumps(state))
