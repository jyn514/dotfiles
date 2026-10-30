#!/usr/bin/env python3
"""Run native tools, replacing the user's input after file has classified it."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


if Path(sys.argv[0]).name == "file":
    result = subprocess.run([os.environ["NATIVE_FILE"], *sys.argv[1:]], check=False)
    os.replace(os.environ["REPLACEMENT"], os.environ["SELECTED_SOURCE"])
    raise SystemExit(result.returncode)

shutil.copyfile(sys.argv[-1], os.environ["CONSUMED_INPUT"])
os.execv(os.environ["NATIVE_GS"], [os.environ["NATIVE_GS"], *sys.argv[1:]])
