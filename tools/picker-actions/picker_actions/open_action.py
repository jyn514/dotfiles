"""Open one or more picker selections with the platform launcher."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from picker_actions.drag import exit_status
from picker_actions.selections import parse


def main(arguments: list[str]) -> int:
    chosen = parse(arguments)
    if chosen is None:
        print("usage: picker-action open [--read0 | [--] selection ...]", file=sys.stderr)
        return 2
    if not chosen:
        return 0

    executable = shutil.which("open")
    if executable is None:
        print("open not found", file=sys.stderr)
        return 127
    positional = [b"./" + value if value.startswith(b"-") else value for value in chosen]
    try:
        result = subprocess.run([os.fsencode(executable), *positional], check=False)
    except OSError as error:
        print(f"could not open selection: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
