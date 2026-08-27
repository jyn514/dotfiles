#!/usr/bin/env python3
"""Merge Plover JSON dictionaries in search-priority order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def merge_dictionaries(paths: list[Path]) -> dict[str, str]:
    """Return one dictionary; earlier paths have higher lookup priority."""
    merged: dict[str, str] = {}
    for path in reversed(paths):
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict) or not all(
            isinstance(outline, str) and isinstance(output, str)
            for outline, output in raw.items()
        ):
            raise ValueError(f"{path}: expected a JSON string-to-string object")
        merged.update(raw)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("dictionaries", type=Path, nargs="+")
    args = parser.parse_args()
    merged = merge_dictionaries(args.dictionaries)
    args.output.write_text(json.dumps(merged, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
