#!/usr/bin/python3
"""Installed guest owner of the GitHub cache; stdin is a bounded binary transfer."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile


def private(path, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
            not directory and info.st_nlink != 1):
        raise ValueError("credential cache has unsafe ownership or permissions")


def memory_filesystem(path):
    result = subprocess.run(["findmnt", "--noheadings", "--output", "FSTYPE", "--target", str(path)],
                            check=True, capture_output=True, text=True, timeout=10)
    if result.stdout.strip() != "tmpfs":
        raise ValueError("credential cache requires guest tmpfs")
    # tmpfs can page out to swap. Do not call a disk-backed swap cache memory-only.
    if len(Path("/proc/swaps").read_text().splitlines()) != 1:
        raise ValueError("credential cache requires a guest without swap")


class Cache:
    def __init__(self, generation, boot, root=None):
        if (not re.fullmatch(r"[0-9a-f]{32}", generation) or
                not re.fullmatch(r"[0-9a-f-]{36}", boot) or
                os.environ.get("SANDBOX_GENERATION") != generation or
                Path("/proc/sys/kernel/random/boot_id").read_text().strip() != boot):
            raise ValueError("credential request names a stale VM generation or boot")
        root = root or Path(f"/run/user/{os.getuid()}")
        private(root, directory=True)
        memory_filesystem(root)
        self.directory = root / "codex-sandbox-credentials"
        for part in (self.directory, self.directory / generation, self.directory / generation / boot):
            part.mkdir(mode=0o700, exist_ok=True)
            private(part, directory=True)
        self.directory = self.directory / generation / boot
        self.token = self.directory / "github-token"

    @contextmanager
    def locked(self):
        path = self.directory / "lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "rb") as lock:
            private(path)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def ready(self):
        if not self.token.exists() and not self.token.is_symlink():
            return False
        private(self.token)
        if not 1 <= self.token.stat().st_size <= 16384:
            raise ValueError("invalid cached credential length")
        return True

    def receive(self, source):
        header = source.read(4)
        if len(header) != 4:
            raise ValueError("credential transfer was interrupted")
        size = struct.unpack("!I", header)[0]
        if not 1 <= size <= 16384:
            raise ValueError("invalid credential transfer length")
        value = source.read(size)
        if len(value) != size or source.read(1) or any(byte in value for byte in (0, 10, 13)):
            raise ValueError("invalid or incomplete credential transfer")
        descriptor, name = tempfile.mkstemp(prefix=".receive-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(value)
            os.replace(name, self.token)
        finally:
            Path(name).unlink(missing_ok=True)


def reply(status, cache):
    print(json.dumps({"status": status, "path": str(cache.token)}), flush=True)


def main():
    operation, generation, boot = sys.argv[1:]
    if operation not in {"ensure", "invalidate"}:
        raise ValueError("unsupported credential operation")
    cache = Cache(generation, boot)
    with cache.locked():
        # Interrupted writers can leave only unpublished tmpfs files. The lock
        # is stable and never removed, including during explicit invalidation.
        for temporary in cache.directory.glob(".receive-*"):
            private(temporary)
            temporary.unlink()
        if operation == "invalidate":
            if cache.ready():
                cache.token.unlink()
            reply("invalidated", cache)
        elif cache.ready():
            reply("ready", cache)
        else:
            reply("missing", cache)
            cache.receive(sys.stdin.buffer)
            reply("ready", cache)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError):
        sys.exit("guest credential operation failed; no credential was published by this request")
