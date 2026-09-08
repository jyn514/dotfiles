"""Assertions inside the real non-root agent image; dummy credential only."""

import os
from pathlib import Path
import socket

assert os.geteuid() != 0, "credential reader elevated the agent command"
assert os.environ["GH_TOKEN"] == "owned-dummy-github-token"
secret = Path("/run/secrets/github-token")
try:
    secret.write_text("changed")
except OSError:
    pass
else:
    raise AssertionError("agent could change the shared boot credential")

source = Path("/repo/agent-write")
source.write_text("live host edit")
source.unlink()
try:
    Path("/repo/.git/agent-write").write_text("changed")
except OSError:
    pass
else:
    raise AssertionError("repository metadata overlay is writable")
assert "nameserver 10.0.2.3" in Path("/etc/resolv.conf").read_text()
assert socket.getaddrinfo("example.com", 443)
print("Non-root credential injection, writable checkout, protected metadata, and DNS passed.")
