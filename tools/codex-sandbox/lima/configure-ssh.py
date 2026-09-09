#!/usr/bin/python3
"""Allow parallel sandbox sessions on Lima's shared SSH connection."""

import os
from pathlib import Path
import subprocess
import tempfile


CONFIG = Path("/etc/ssh/sshd_config.d/00-codex-sandbox.conf")


def replace_config(path, contents):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure(path=CONFIG):
    if path.is_symlink():
        raise ValueError("SSH configuration must not be a symlink")
    previous = path.read_bytes() if path.exists() else None
    replace_config(path, b"# Parallel sandbox sessions share Lima's SSH connection.\nMaxSessions 20\n")
    try:
        subprocess.run(["/usr/sbin/sshd", "-t"], check=True)
        effective = subprocess.run(["/usr/sbin/sshd", "-T"], check=True,
                                   capture_output=True, text=True).stdout
        if "maxsessions 20" not in effective.splitlines():
            raise ValueError("another SSH setting overrides MaxSessions 20")
    except BaseException:
        if previous is None:
            path.unlink()
        else:
            replace_config(path, previous)
        raise
    # Reload keeps existing connections alive; new connections use the limit.
    subprocess.run(["systemctl", "reload", "ssh"], check=True)


if __name__ == "__main__":
    if os.getuid() != 0:
        raise SystemExit("SSH configuration requires root")
    configure()
