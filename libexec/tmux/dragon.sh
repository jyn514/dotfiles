#!/usr/bin/env python3
"""Launch Dragon for direct or NUL-delimited selections."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/picker-actions"))

from picker_actions.drag import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
