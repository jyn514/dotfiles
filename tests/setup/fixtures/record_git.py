#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

with Path(os.environ['GIT_TEST_LOG']).open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\n')
