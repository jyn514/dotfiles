#!/usr/bin/env python3
"""Exec the real directory validator with the invoking fixture's owned HOME."""

import os
from pathlib import Path
import sys


invoked = Path(__file__).absolute()
launcher = invoked.resolve().parents[2] / "codex-sandbox"
os.environ["HOME"] = str(invoked.parent / "home")
os.execv(str(launcher), [str(launcher), *sys.argv[1:]])
