#!/usr/bin/python3
"""Install the pinned transport before Lima starts rootless containerd."""

import hashlib
import os
from pathlib import Path
import platform
import shutil
import stat
import tempfile
from urllib.request import urlopen


URL = "https://github.com/rootless-containers/slirp4netns/releases/download/v1.3.5/slirp4netns-aarch64"
SHA256 = "a212e7acabf09e809b62ca62d1721ecab0d811d05c378ea0270ce29a70d986df"
DESTINATION = Path("/usr/local/bin/slirp4netns")


def verify(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        raise ValueError("slirp4netns must be an owned regular file without group/other write access")
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != SHA256:
            raise ValueError("slirp4netns checksum differs from the pinned release")


def install(destination=DESTINATION):
    if destination.exists() or destination.is_symlink():
        verify(destination)
        if destination.stat().st_mode & 0o111 != 0o111:
            raise ValueError("installed slirp4netns is not executable")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep download and checksum failure outside the executable path, and publish
    # on the same filesystem so an interrupted download cannot poison startup.
    with tempfile.TemporaryDirectory(prefix=".slirp4netns-", dir=destination.parent) as directory:
        staged = Path(directory) / "slirp4netns"
        with urlopen(URL, timeout=60) as response, staged.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify(staged)
        staged.chmod(0o755)
        os.replace(staged, destination)


if __name__ == "__main__":
    if os.geteuid() != 0 or platform.system() != "Linux" or platform.machine() != "aarch64":
        raise SystemExit("this provisioning hook requires a root-owned aarch64 Linux guest")
    install()
