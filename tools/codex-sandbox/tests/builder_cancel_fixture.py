"""Owned stand-in for an executable builder and its nested Buildx process."""

import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docker_runtime import Docker

mode, directory = sys.argv[1:]
root = Path(directory)
if mode == 'child':
    (root / 'child').write_text(str(os.getpid()))
    time.sleep(60)
else:
    (root / 'ready').write_text(str(os.getpid()))
    runtime = object.__new__(Docker)
    runtime.host = SimpleNamespace(state=root)
    runtime.verify = lambda: None
    runtime.argv = lambda arguments: [sys.executable, __file__, 'child', directory]
    runtime.builder_arguments = lambda arguments: arguments
    runtime.build('unused', root / 'Dockerfile', root)
