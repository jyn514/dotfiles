#!/usr/bin/env python3
"""Show the native Pi inputs selected by the wrapper on an owned test home."""

import json
import os
import sys

print(json.dumps({
    "arguments": sys.argv[1:],
    "sandbox_environment": {
        key: value for key, value in os.environ.items()
        if key.startswith("CODEX_SANDBOX_")
    },
}))
raise SystemExit(int(os.environ.get("HOST_PI_FIXTURE_EXIT", "0")))
