"""Run launcher integration tests with proxy lifecycle calls at a fake boundary."""

from pathlib import Path
import runpy
import subprocess
import sys


tool = Path(__file__).resolve().parents[1]
launcher = runpy.run_path(str(tool / "codex-sandbox"))


def helper(*arguments: str, check: bool = True):
    # The fixture's PATH provides the existing fake proxy helper process.
    return subprocess.run(["python3", str(tool / "sandbox-proxies.py"), *arguments], check=check)


launcher["main"].__globals__["helper"] = helper
raise SystemExit(launcher["main"](sys.argv[1:]))
