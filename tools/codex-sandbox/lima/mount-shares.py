#!/usr/bin/python3
"""Repair Lima 1.2.1 fstab escaping before accepting host shares."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def escaped(path):
    return path.replace("\\", "\\134").replace(" ", "\\040")


def repair(text, shares):
    lines = text.splitlines(keepends=True)
    for index, share in enumerate(shares):
        tag = f"mount{index}"
        path = share["mountPoint"]
        options = ("rw" if share["writable"] else "ro") + ",nofail,comment=cloudconfig"
        raw = "\t".join((tag, path, "virtiofs", options, "0", "0")) + "\n"
        fixed = "\t".join((tag, escaped(path), "virtiofs", options, "0", "0")) + "\n"
        matches = [position for position, line in enumerate(lines) if line.startswith(tag + "\t")]
        if len(matches) != 1 or lines[matches[0]] not in (raw, fixed):
            raise ValueError(f"refusing to replace an unexpected fstab entry for {tag}")
        lines[matches[0]] = fixed
    return "".join(lines)


def main():
    if os.getuid() != 0:
        raise ValueError("mount provisioning requires guest root")
    shares = json.load(sys.stdin)["shares"]
    destination = Path("/etc/fstab")
    original = destination.read_text()
    fixed = repair(original, shares)
    if fixed != original:
        descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".sandbox-fstab-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(fixed)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=30)
    for index, share in enumerate(shares):
        target = share["mountPoint"]
        mounted = subprocess.run(["mountpoint", "--quiet", "--", target], timeout=30)
        if mounted.returncode == 0:
            continue  # The read-only preflight checks filesystem, tag, and mode.
        if mounted.returncode != 32:
            raise ValueError(f"cannot inspect mount point: {target}")
        Path(target).mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", "-t", "virtiofs", "-o", "rw" if share["writable"] else "ro",
                        f"mount{index}", target], check=True, timeout=30)


if __name__ == "__main__":
    main()
