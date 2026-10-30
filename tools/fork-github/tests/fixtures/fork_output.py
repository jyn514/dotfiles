#!/usr/bin/env python3
"""Model a producer that returns no path or fails after emitting a path."""

import os
import sys

sys.stdout.write(os.environ.get("FORK_OUTPUT", ""))
raise SystemExit(int(os.environ.get("FORK_STATUS", "0")))
