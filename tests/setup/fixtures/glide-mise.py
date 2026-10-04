#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

Path(os.environ["GLIDE_TEST_LOG"]).write_text(
    json.dumps([sys.argv[1:], os.environ.get("MISE_AUTO_INSTALL")])
)
