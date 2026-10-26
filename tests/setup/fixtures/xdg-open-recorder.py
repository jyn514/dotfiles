#!/usr/bin/env python3

import json
import os
from pathlib import Path
import sys


Path(os.environ["XDG_OPEN_TEST_LOG"]).write_text(json.dumps(sys.argv))
