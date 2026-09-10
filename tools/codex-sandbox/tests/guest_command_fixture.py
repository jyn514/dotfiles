"""Echo transport inputs, then fail with a distinctive status."""

import json
import os
import sys

print(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(),
                  'stdin': sys.stdin.buffer.read().hex()}))
sys.exit(37)
