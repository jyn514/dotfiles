#!/usr/bin/python3
"""Mount Lima shares and repair virtiofs paths before accepting host shares."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mounts import lima_tag


def escaped(path):
    return path.replace("\\", "\\134").replace(" ", "\\040")


def mount_9p(share):
    cache = "mmap" if share["writable"] else "fscache"
    options = ",".join(("rw" if share["writable"] else "ro", "trans=virtio",
                         "version=9p2000.L", "msize=131072", f"cache={cache}"))
    subprocess.run(["mount", "-t", "9p", "-o", options, lima_tag(share),
                    share["mountPoint"]], check=True, timeout=30)


def repair(text, shares, mount_type="virtiofs"):
    lines = text.splitlines(keepends=True)
    for index, share in enumerate(shares):
        tag = f"mount{index}"
        path = share["mountPoint"]
        matches = [position for position, line in enumerate(lines) if line.split()[:1] == [tag]]
        if len(matches) != 1:
            actual = [lines[position].rstrip("\n") for position in matches]
            raise ValueError(
                f"refusing to replace fstab entry for {tag}: expected one entry, actual={actual!r}"
            )
        line = lines[matches[0]].rstrip("\n")
        delimiter = "\t" if "\t" in line else " "
        fields = line.split(delimiter) if delimiter == "\t" else line.split()
        mode = "rw" if share["writable"] else "ro"
        if (len(fields) != 6 or fields[0] != tag or fields[1] not in (path, escaped(path)) or
                fields[2] != mount_type or mode not in fields[3].split(",")):
            raise ValueError(
                f"refusing to replace fstab entry for {tag}: "
                f"expected source={tag!r}, target={escaped(path)!r}, fstype={mount_type!r}, mode={mode!r}; "
                f"actual={line!r}"
            )
        fields[1] = escaped(path)
        lines[matches[0]] = delimiter.join(fields) + "\n"
    return "".join(lines)


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
    destination = Path("/etc/fstab")
    if mount_type != "9p":
        original = destination.read_text()
        fixed = repair(original, shares, mount_type)
    else:
        original = fixed = None
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
