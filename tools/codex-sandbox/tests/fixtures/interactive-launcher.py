import runpy
import sys
from pathlib import Path

launcher = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'codex-sandbox'))
original = launcher['run_agent']

def benchmark(state, arguments):
    return original(state, ['--env', 'PI_STARTUP_BENCHMARK=1', *arguments])

original.__globals__['run_agent'] = benchmark
raise SystemExit(launcher['main'](sys.argv[1:]))
