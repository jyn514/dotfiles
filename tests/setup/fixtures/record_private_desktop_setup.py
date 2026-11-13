#!/usr/bin/python3
"""Record setup dispatch without building or changing the host."""
import json
import os
from pathlib import Path
import sys

Path(os.environ["PRIVATE_DESKTOP_SETUP_LOG"]).write_text(json.dumps(sys.argv[1:]))
