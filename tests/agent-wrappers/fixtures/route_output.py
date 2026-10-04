#!/usr/bin/env python3
"""Malformed or failed route publication for decoder regression tests."""
import json
import os
import sys

mode = os.environ["JJ_TEST_ROUTE_MODE"]
result = {"backend": "native", "workspace": None, "destination": None,
          "command": ["status"], "hooks": False}
if mode == "relative":
    result["workspace"] = "relative"
print(json.dumps(result))
if mode == "duplicate":
    print(json.dumps(result))
if mode == "failed":
    print("jj route fixture: failed after producing output", file=sys.stderr)
    raise SystemExit(9)
