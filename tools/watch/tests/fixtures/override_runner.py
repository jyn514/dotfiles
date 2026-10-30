#!/usr/bin/env python3
"""An override must keep subprocess.run's cancellation, not cooperative waiting."""
import json
import os
from pathlib import Path
import signal
import sys
import time

signal.signal(signal.SIGINT, signal.SIG_IGN)
with Path(os.environ["WATCH_TEST_OVERRIDE_LOG"]).open("a") as stream:
    stream.write(json.dumps({"event": "start", "pid": os.getpid(), "pgid": os.getpgrp(), "argv": sys.argv[1:]}) + "\n")
time.sleep(60)
