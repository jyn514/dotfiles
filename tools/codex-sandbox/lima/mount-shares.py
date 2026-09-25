#!/usr/bin/python3
"""Repair Lima-generated fstab escaping before accepting host shares."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def escaped(path):
    return path.replace("\\", "\\134").replace(" ", "\\040")


def repair(text, shares, mount_type="virtiofs"):
    lines = text.splitlines(keepends=True)
    for index, share in enumerate(shares):
        tag = f"mount{index}"
        path = share["mountPoint"]
        matches = [position for position, line in enumerate(lines) if line.split()[:1] == [tag]]
        if len(matches) != 1:
            raise ValueError(f"refusing to replace an unexpected fstab entry for {tag}")
        line = lines[matches[0]].rstrip("\n")
        delimiter = "\t" if "\t" in line else " "
        fields = line.split(delimiter) if delimiter == "\t" else line.split()
        required = {"rw" if share["writable"] else "ro", "nofail", "comment=cloudconfig"}
        if (len(fields) != 6 or fields[0] != tag or fields[1] not in (path, escaped(path)) or
                fields[2] != mount_type or not required.issubset(fields[3].split(",")) or
                fields[4:] != ["0", "0"]):
            raise ValueError(f"refusing to replace an unexpected fstab entry for {tag}")
        fields[1] = escaped(path)
        lines[matches[0]] = delimiter.join(fields) + "\n"
    return "".join(lines)


def main():
    if os.getuid() != 0:
        raise ValueError("mount provisioning requires guest root")
    record = json.load(sys.stdin)
    shares = record["shares"]
    mount_type = record.get("mount_type", "virtiofs")
    destination = Path("/etc/fstab")
    original = destination.read_text()
    fixed = repair(original, shares, mount_type)
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
        subprocess.run(["mount", "--target", target], check=True, timeout=30)


if __name__ == "__main__":
    main()
