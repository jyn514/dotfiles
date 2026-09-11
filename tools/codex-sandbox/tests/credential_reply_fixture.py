"""Exercise the host's framed credential exchange over real subprocess pipes."""
import json
import struct
import sys

replies = json.loads(sys.argv[1])
if not replies:
    sys.exit(1)
print(json.dumps(replies[0]), flush=True)
payload = sys.stdin.buffer.read()
if replies[0]['status'] == 'missing':
    assert payload == struct.pack('!I', 5) + b'dummy'
else:
    assert not payload
for reply in replies[1:]:
    print(json.dumps(reply), flush=True)
