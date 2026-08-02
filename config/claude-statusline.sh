#!/usr/bin/env python3
"""Execute the Claude render target from the installed dotfiles tree."""

import os
from pathlib import Path
import sys


def main() -> int:
    command = Path(__file__).resolve().parents[1] / "bin/prompt-command"
    try:
        os.execv(command, [str(command), "claude"])
    except OSError as error:
        print(f"claude-statusline: could not execute renderer: {error}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
