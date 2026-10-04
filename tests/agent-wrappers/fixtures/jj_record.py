#!/usr/bin/env python3
"""Record wrapper dispatch without modifying a repository or connecting a socket."""
import json
import os
from pathlib import Path
import sys

role = Path(sys.argv[0]).name
with open(os.environ["JJ_TEST_RECORD"], "a", encoding="utf-8") as output:
    output.write(json.dumps({
        "role": role, "argv": sys.argv[1:], "cwd": os.getcwd(),
        "user": os.environ.get("JJ_USER"), "email": os.environ.get("JJ_EMAIL"),
        "proxy": os.environ.get("SANDBOX_PROXY_DIR"),
    }) + "\n")
if "metaedit" in sys.argv[1:]:
    raise SystemExit(int(os.environ.get("JJ_TEST_HOOK_EXIT", "0")))
raise SystemExit(int(os.environ.get("JJ_TEST_MAIN_EXIT", "0")))
