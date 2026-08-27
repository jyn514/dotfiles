#!/usr/bin/env python3
"""Fetch and verify the fixed held-out coverage corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "heldout_corpora.json")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    entries = json.loads(args.manifest.read_text())
    for entry in entries:
        with urllib.request.urlopen(entry["url"]) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(
                f"checksum mismatch for {entry['name']}: {digest}"
            )
        destination = args.directory / entry["name"]
        destination.write_bytes(data)
        print(destination)


if __name__ == "__main__":
    main()
