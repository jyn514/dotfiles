#!/usr/bin/env python3
"""Exec real directory validation; simulate a failing build only for native UI tests."""

import os
import signal
from pathlib import Path
import sys


invoked = Path(__file__).absolute()
launcher = invoked.resolve().parents[2] / "codex-sandbox"
os.environ["HOME"] = str(invoked.parent / "home")
if sys.argv[1:2] == ["prepare-cd"]:
    (invoked.parent / "build-request").write_text(sys.argv[2])
    if (invoked.parent / "kill-build").exists():
        os.kill(os.getpid(), signal.SIGKILL)
    print("Cannot find module './identity.js'", file=sys.stderr)
    sys.exit(1)
os.execv(str(launcher), [str(launcher), *sys.argv[1:]])
