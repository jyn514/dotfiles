"""Simulate a Docker wrapper exiting before its Buildx plugin."""

from pathlib import Path
import subprocess
import sys

child = subprocess.Popen(['sleep', '300'])
Path(sys.argv[1]).write_text(str(child.pid))
raise SystemExit(int(sys.argv[2]))
