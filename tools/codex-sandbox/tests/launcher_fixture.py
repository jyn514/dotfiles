"""Run launcher integration tests with proxy lifecycle calls at a fake boundary."""

from pathlib import Path
import os
import runpy
import subprocess
import sys


tool = Path(__file__).resolve().parents[1]
launcher = runpy.run_path(str(tool / "codex-sandbox"))


def helper(*arguments: str, check: bool = True):
    # The fixture's PATH provides the existing fake proxy helper process.
    return subprocess.run(["python3", str(tool / "sandbox-proxies.py"), *arguments], check=check)


launcher["main"].__globals__["helper"] = helper
acquire = launcher['acquire_lock']

def acquire_lock(state):
    acquire(state)
    # The sidecar fixtures supply an existing publication through FAKE_PROXY_STATE.
    if os.environ.get('FAKE_SESSION') == 'shared':
        state.proxy_lock.shared = True
        state.proxy_lock.release_coordination()

launcher['main'].__globals__['acquire_lock'] = acquire_lock
raise SystemExit(launcher["main"](sys.argv[1:]))
