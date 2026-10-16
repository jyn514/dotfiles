#!/usr/bin/env python3
"""Report which disposable executable a test-environment child selected."""
import json
from pathlib import Path
import sys


if __name__ == "__main__":
    print(json.dumps({"executable": str(Path(__file__).resolve()), "arguments": sys.argv[1:]}))
