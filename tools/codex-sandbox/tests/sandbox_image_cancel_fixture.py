"""Run the real image CLI around a disposable detached builder group."""

import os
from pathlib import Path
import runpy
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bake
from docker_runtime import Docker
import sandbox_runtime

directory = Path(sys.argv[1])
runtime = object.__new__(Docker)
runtime.builder_environment = lambda: os.environ.copy()
runtime.build_platform = lambda: 'linux/arm64'
sandbox_runtime.image_runtime = lambda *_: runtime


def resolve(*args, **kwargs):
    with tempfile.TemporaryDirectory(prefix='capture-', dir=directory):
        runtime.run_builder([
            sys.executable, str(ROOT / 'tests/builder_orphan_fixture.py'),
            str(directory / 'child'), '0',
        ])
    return {}


bake.resolve = resolve
sys.argv = ['sandbox-image', 'bake', '--platform', 'linux/arm64', 'base']
runpy.run_path(str(ROOT / 'sandbox-image'), run_name='__main__')
