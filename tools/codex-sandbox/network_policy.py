"""Authoritative outer-workload policy; provisioning snapshots these bytes."""

import json
from pathlib import Path


PROHIBITED_ROUTES = (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
)


def policy_bytes():
    network = json.loads((Path(__file__).parent / "lima/rootless-network.json").read_text())
    # Keep serialization stable: installed hosts pin the digest of these bytes.
    return json.dumps({"version": 2, "ipv6": "disabled", "dns": network["dns"],
                       "prohibited": PROHIBITED_ROUTES}).encode()
