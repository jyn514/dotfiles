#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <destination> <source>", file=sys.stderr)
        return 2

    destination = Path(os.path.abspath(sys.argv[1])).relative_to(Path.home())
    config_path = Path("install.conf.json")
    config = json.loads(config_path.read_text())
    links = next(directive["link"] for directive in config if "link" in directive)
    links[f"$HOME/{destination}"] = sys.argv[2]
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
