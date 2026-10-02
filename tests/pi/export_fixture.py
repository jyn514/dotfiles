#!/usr/bin/env python3
"""Dummy native Pi receiver for launcher and batch-export tests."""

import os
from pathlib import Path
import sys


def main() -> int:
    if os.environ.get("PI_EXPORT_FIXTURE_FAIL"):
        print("Native export refused", file=sys.stderr)
        return 7
    arguments = sys.argv[1:]
    if len(arguments) not in (2, 3) or arguments[0] != "--export":
        print(f"Unexpected native Pi arguments: {arguments!r}", file=sys.stderr)
        return 2
    source = Path(arguments[1])
    output = Path(arguments[2]) if len(arguments) == 3 else Path(f"pi-session-{source.stem}.html")
    output.write_text(f"<html>{source.read_text()}</html>")
    print(f"Exported to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
