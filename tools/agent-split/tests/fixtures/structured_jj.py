#!/usr/bin/env python3
"""Record agent-split's public-wrapper calls without contacting a proxy."""

import json
import os
import subprocess
import sys

assert os.getcwd() == os.environ["STRUCTURED_JJ_WORKSPACE"]
assert os.environ["CALLER_MARKER"] == "preserved"
assert "SANDBOX_PROXY_DIR" not in os.environ

with open(os.environ["STRUCTURED_JJ_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")

if sys.argv[1:2] == ["--agent-split"]:
    sys.exit(17)

sys.exit(subprocess.call([os.environ["JJ_REAL"], *sys.argv[1:]]))
