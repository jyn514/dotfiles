#!/usr/bin/env python3
"""Stop watch after one frame without touching a live terminal."""
from pathlib import Path
import sys

sys.exit(31 if Path(sys.argv[0]).name == "sleep" else 0)
