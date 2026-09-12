"""Dummy security child for relay lifecycle tests; never reads Keychain."""

import os
import signal
import sys
import time

mode, account, ready = sys.argv[1:]
if mode == 'stall':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.write(int(ready), b'1')
os.close(int(ready))
if mode == 'deny-first' or (mode == 'deny-second' and account == 'secret-key'):
    sys.stderr.write('private-canary-error')
    sys.exit(1)
if mode == 'oversize':
    sys.stdout.write('x' * 8192)
elif mode == 'stall':
    print('ready', flush=True)
    time.sleep(60)
else:
    print('canary-' + account)
