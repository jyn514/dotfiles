"""Record Git's SSH transport arguments without starting SSH or using the network."""

import json
import os
from pathlib import Path
import sys


Path(os.environ["SSH_RECORD"]).write_text(json.dumps(sys.argv[1:]))
# Stop before Git's protocol exchange; endpoint selection has already happened.
raise SystemExit(1)
