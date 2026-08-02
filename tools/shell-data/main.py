#!/usr/bin/env python3
"""Validate the repository abbreviation data file."""

from pathlib import Path
import sys

from shell_data.abbreviations import validate


def main(arguments: list[str]) -> int:
    if len(arguments) > 1:
        print("usage: tools/shell-data/main.py [abbr-file]", file=sys.stderr)
        return 2
    path = Path(arguments[0]) if arguments else Path(__file__).resolve().parents[2] / "lib/abbr.txt"
    try:
        contents = path.read_bytes()
    except OSError as error:
        print(f"{path}: {error}", file=sys.stderr)
        return 1
    _entries, diagnostics = validate(contents)
    for diagnostic in diagnostics:
        print(f"{path}:{diagnostic}", file=sys.stderr)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
