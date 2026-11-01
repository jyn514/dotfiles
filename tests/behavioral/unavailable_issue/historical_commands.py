#!/usr/bin/env python3
"""Issue-command substitute inside the disposable historical worker."""
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
arguments = sys.argv[1:]
config = json.loads(Path('/task/commands.json').read_text())
if arguments[:1] == ['bug']:
    if config['mode'] == 'unreadable':
        sys.stderr.write(config['failure']['output'])
        sys.exit(config['failure']['exit_code'])
    sys.stdout.write(Path('/task/issue.md').read_text())
    sys.exit(0)
os.execv(config['executables'][name], [config['executables'][name], *arguments])
