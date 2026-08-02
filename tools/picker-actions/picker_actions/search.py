"""Open one picker selection as a web search."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from urllib.parse import urlencode

from picker_actions.drag import exit_status
from picker_actions.selections import parse


def main(arguments: list[str]) -> int:
    chosen = parse(arguments)
    if chosen is None:
        print("usage: picker-action search [--read0 | [--] selection]", file=sys.stderr)
        return 2
    if not chosen:
        return 0
    if len(chosen) != 1:
        print("search requires exactly one selection", file=sys.stderr)
        return 2

    executable = shutil.which("open")
    if executable is None:
        print("open not found", file=sys.stderr)
        return 127
    url = b"https://www.google.com/search?" + urlencode({b"q": chosen[0]}).encode("ascii")
    try:
        result = subprocess.run([os.fsencode(executable), url], check=False)
    except OSError as error:
        print(f"could not open search: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
