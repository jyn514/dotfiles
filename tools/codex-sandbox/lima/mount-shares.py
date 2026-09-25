#!/usr/bin/python3
"""Mount Lima shares before accepting host shares."""

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mounts import lima_tag


def mount_9p(share):
    cache = "mmap" if share["writable"] else "fscache"
    options = ",".join(("rw" if share["writable"] else "ro", "trans=virtio",
                         "version=9p2000.L", "msize=131072", f"cache={cache}"))
    subprocess.run(["mount", "-t", "9p", "-o", options, lima_tag(share),
                    share["mountPoint"]], check=True, timeout=30)

def main():
    if os.getuid() != 0:
        raise ValueError("mount provisioning requires guest root")
    record = json.load(sys.stdin)
    shares = record["shares"]
    mount_type = record.get("mount_type", "virtiofs")
    for share in shares:
        target = share["mountPoint"]
        mounted = subprocess.run(["mountpoint", "--quiet", "--", target], timeout=30)
        if mounted.returncode == 0:
            continue  # The read-only preflight checks filesystem, tag, and mode.
        if mounted.returncode != 32:
            raise ValueError(f"cannot inspect mount point: {target}")
        Path(target).mkdir(parents=True, exist_ok=True)
        if mount_type == "9p":
            mount_9p(share)
    for share in shares:
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
