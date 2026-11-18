#!/usr/bin/env python3
"""Record sandbox startup and echo the launcher's forwarded arguments."""

import os
from pathlib import Path
import sys

Path(os.environ["PI_SANDBOX_FIXTURE_RECORD"]).touch()
for argument in sys.argv[1:]:
    print(argument)
