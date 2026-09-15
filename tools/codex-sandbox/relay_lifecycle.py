"""Shared resource topology and recovery projection for per-launch relays."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trusted_services import ResourceTopology


@dataclass(frozen=True)
class RelayResourcePlan:
    link_network: str
    egress_network: str
    container: str

    def bound_topology(self) -> Mapping[str, tuple[str, ...]]:
        return ResourceTopology({
            "link-network": (),
            "egress-network": (),
            "relay-container": ("link-network", "egress-network"),
        }).bind({
            "link-network": f"network:{self.link_network}",
            "egress-network": f"network:{self.egress_network}",
            "relay-container": f"container:{self.container}",
        })

    def recovery_resources(self, remaining: tuple[str, ...], owner: str) -> list[dict[str, object]]:
        topology = self.bound_topology()
        resources = []
        for identity in remaining:
            if identity not in topology:
                continue
            kind, _, name = identity.partition(":")
            dependencies = [dependency.partition(":")[2]
                            for dependency in topology[identity]]
            resources.append({
                "kind": kind,
                "name": name,
                "owner": owner,
                "dependencies": dependencies,
            })
        return resources
