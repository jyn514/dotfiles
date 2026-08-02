"""Copy one picker selection to the clipboard."""

from __future__ import annotations

import shutil
import subprocess
import sys

from picker_actions.drag import exit_status
from picker_actions.selections import parse


def main(arguments: list[str]) -> int:
    primary = bool(arguments and arguments[0] == "--primary")
    if primary:
        arguments = arguments[1:]
    chosen = parse(arguments)
    if chosen is None:
        print(
            "usage: picker-action copy [--primary] [--read0 | [--] selection]",
            file=sys.stderr,
        )
        return 2
    if not chosen:
        return 0
    if len(chosen) != 1:
        print("copy requires exactly one selection", file=sys.stderr)
        return 2

    executable = shutil.which("copy")
    if executable is None:
        print("copy not found", file=sys.stderr)
        return 127
    command = [executable]
    if primary:
        command.append("--primary")
    try:
        result = subprocess.run(command, check=False, input=chosen[0])
    except OSError as error:
        print(f"could not copy selection: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
