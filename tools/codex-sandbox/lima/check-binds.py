"""Read-only guest checks for host-resolved bind sources supplied as JSON."""

import hashlib
import json
import os
from pathlib import Path
import sys


def check_binds(bindings):
    for binding in bindings:
        path = Path(binding["source"])
        kind = binding["kind"]
        if kind == "directory":
            matches = path.is_dir()
        elif kind == "file":
            matches = path.is_file()
        else:
            raise ValueError("unsupported bind source type")
        if not matches:
            raise ValueError(f"guest bind source is not a {kind}: {path}")
        if not os.access(path, os.R_OK):
            raise ValueError(f"guest bind source is not readable: {path}")
        if binding["writable"] and not os.access(path, os.W_OK):
            raise ValueError(f"guest bind source is not writable: {path}")
        if kind == "file":
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != binding["sha256"]:
                raise ValueError(f"guest bind source differs from the host: {path}")


if __name__ == "__main__":
    try:
        check_binds(json.load(sys.stdin))
    except (ValueError, OSError, KeyError, TypeError) as error:
        sys.exit(str(error))
