#!/usr/bin/env python3
"""Exercise the protected read/mutation boundary without contacting a proxy."""

import json
import os
import subprocess
import sys

assert os.getcwd() == os.environ["STRUCTURED_JJ_WORKSPACE"]
assert os.environ["CALLER_MARKER"] == "preserved"
assert "SANDBOX_PROXY_DIR" not in os.environ

arguments = sys.argv[1:]
inspect = bool(os.environ.get("JJ_PROXY_INSPECT"))
with open(os.environ["STRUCTURED_JJ_LOG"], "a") as log:
    log.write(json.dumps({"args": arguments, "inspect": inspect}) + "\n")

# Match the actual proxy contract: neither mode accepts caller operation flags.
if any(arg.split("=", 1)[0] in {"--ignore-working-copy", "--at-operation", "--at-op"}
       for arg in arguments):
    print("proxy policy rejects caller security-sensitive options", file=sys.stderr)
    sys.exit(125)

if arguments[:1] == ["--agent-split"]:
    assert not inspect, "structured split must remain a mutation request"
    sys.exit(17)

if arguments[:1] == ["status"]:
    assert not inspect, "initial snapshot must remain a mutation request"
    sys.exit(subprocess.call([os.environ["JJ_REAL"], *arguments]))

assert arguments[0] in {"workspace", "log", "diff", "file", "git"}
assert inspect, "revision queries must use the supported inspection request mode"
# Emulate the trusted executor's injection, not a caller option.
sys.exit(subprocess.call([os.environ["JJ_REAL"], arguments[0],
                          "--ignore-working-copy", *arguments[1:]]))
