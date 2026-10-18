#!/usr/bin/env python3
"""Read the importer's Codex profile as thread configuration overrides."""

import json
from pathlib import Path
import sys
import tomllib

with Path(sys.argv[1]).open("rb") as source:
    json.dump(tomllib.load(source), sys.stdout)
