#!/usr/bin/env python3
"""Execute an unmodified source wrapper without an installed image helper."""
from pathlib import Path
import sys

mode = sys.argv[1]
sys.argv = sys.argv[2:]
source = Path(sys.argv[0])
code = compile(source.read_bytes(), str(source), 'exec')
original_is_file = Path.is_file


def source_only(path):
    if path == Path('/tools/jj-proxy/route.py'):
        return False
    return original_is_file(path)


Path.is_file = source_only
if mode == 'unlink':
    source.unlink()
exec(code, {'__name__': '__main__', '__file__': str(source)})
