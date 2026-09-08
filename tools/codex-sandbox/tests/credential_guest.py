"""Dummy-only workload demonstrating in-agent environment injection."""

import os
from pathlib import Path

assert "GH_TOKEN" not in os.environ
path = Path("/run/secrets/github-token")
os.environ["GH_TOKEN"] = path.read_text()
assert os.environ["GH_TOKEN"] == "owned-dummy-github-token"
try:
    path.write_text("changed")
except OSError:
    pass
else:
    raise AssertionError("agent could modify the shared boot credential")
print("Read-only memory mount supplied GH_TOKEN inside the agent.")
