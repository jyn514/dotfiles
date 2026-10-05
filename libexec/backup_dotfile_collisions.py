#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

from dotfile_links import configured_links


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <dotbot config>", file=sys.stderr)
        return 2

    config_path = Path(sys.argv[1]).resolve()
    backup_directory = Path.home() / ".local/config"
    backup_directory.mkdir(parents=True, exist_ok=True)

    for destination_name, source in configured_links(config_path).items():
        destination = Path(os.path.expanduser(os.path.expandvars(destination_name)))
        if destination.is_symlink() or not destination.exists():
            continue
        if os.path.samefile(source, destination):
            continue
        subprocess.run(["mv", str(destination), str(backup_directory)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
