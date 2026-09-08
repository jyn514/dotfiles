#!/usr/bin/python3
"""Install the public network in an owned VM before publishing it as ready."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def validate(config):
    identity = config.get("nerdctlID", "")
    if not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("invalid public network identity")
    expected = {
        "cniVersion": "1.0.0", "name": "codex-public-only", "nerdctlID": identity,
        "plugins": [
            {"type": "bridge", "bridge": "br-" + identity[:12], "isGateway": True,
             "ipMasq": True, "hairpinMode": True,
             "ipam": {"type": "host-local", "routes": [{"dst": "0.0.0.0/0"}],
                      "ranges": [[{"gateway": "10.254.254.1", "subnet": "10.254.254.0/24",
                                   "ipRange": "10.254.254.128/25", "rangeStart": "10.254.254.129",
                                   "rangeEnd": "10.254.254.255"}]]}},
            {"type": "portmap", "capabilities": {"portMappings": True}},
            {"type": "firewall", "backend": "iptables", "ingressPolicy": "same-bridge"},
            {"type": "tuning"},
        ],
    }
    plugins = config.get("plugins", [])
    if plugins and plugins[-1].get("type") == "public-only":
        plugins = plugins[:-1]
    if {**config, "plugins": plugins} != expected:
        raise ValueError("existing public network differs from the validated bridge configuration")


def main():
    name = "codex-public-only"
    directory = Path.home() / ".config/cni/net.d/default"
    destination = directory / f"nerdctl-{name}.conflist"
    if not destination.exists():
        subprocess.run(["nerdctl", "--namespace", "default", "network", "create",
                        "--subnet", "10.254.254.0/24", "--gateway", "10.254.254.1",
                        "--ip-range", "10.254.254.128/25", name], check=True, timeout=30)
    config = json.loads(destination.read_text())
    validate(config)
    policy = Path("/usr/local/share/codex-sandbox/network-policy.json").read_bytes()
    plugin = {"type": "public-only", "policyDigest": hashlib.sha256(policy).hexdigest()}
    existing = [item for item in config["plugins"] if item["type"] == "public-only"]
    if existing:
        if existing != [plugin] or config["plugins"][-1] != plugin:
            raise ValueError("existing public network has incompatible policy")
        return
    config["plugins"].append(plugin)
    descriptor, temporary = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(config, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
