"""Record mocked shell command argv without performing the command."""
import json
import os
from pathlib import Path
import sys

with Path(os.environ["FIXTURE_LOG"]).open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\n")
