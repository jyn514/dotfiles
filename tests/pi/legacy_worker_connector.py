"""One old-worker rejection frame, captured from its request validator."""
import json
import sys

request = json.loads(sys.stdin.readline())
mode = request.get("params", {}).get("mode")
if mode == "duplicate":
    print('{"kind":"result","result":1}\n{"kind":"result","result":2}', flush=True)
elif mode == "oversize":
    print("x" * (33 * 1024 * 1024), flush=True)
elif mode == "boundary":
    print(json.dumps({"kind": "error", "message": "worker refused", "boundary": {"error": "checkpoint failed"}}), flush=True)
elif mode == "invalid-boundary":
    print(json.dumps({"kind": "result", "result": {}, "boundary": {"error": 7}}), flush=True)
elif "entry" in request:
    print(json.dumps({"kind": "error", "message": "invalid tool request"}), flush=True)
else:
    print(json.dumps({"kind": "error", "message": "unknown tool"}), flush=True)
