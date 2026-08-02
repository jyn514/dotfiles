#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path


def links(config_path: Path) -> dict[str, object]:
    config = json.loads(config_path.read_text())
    return next(directive["link"] for directive in config if "link" in directive)


def source_path(repository: Path, specification: object) -> Path:
    if isinstance(specification, str):
        path = specification
    else:
        path = specification["path"]
    return repository / path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <dotbot config>", file=sys.stderr)
        return 2

    config_path = Path(sys.argv[1]).resolve()
    repository = config_path.parent
    backup_directory = Path.home() / ".local/config"
    backup_directory.mkdir(parents=True, exist_ok=True)

    for destination_name, specification in links(config_path).items():
        destination = Path(
            os.path.expanduser(os.path.expandvars(destination_name))
        )
        source = source_path(repository, specification)
        if destination.is_symlink() or not destination.exists():
            continue
        if os.path.samefile(source, destination):
            continue
        subprocess.run(["mv", str(destination), str(backup_directory)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
