#!/usr/bin/python3
"""Installed creator of isolated per-launch relay links and relay egress networks."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import os


def configure(config, internal, public_service=False):
    plugins = config["plugins"]
    if ([plugin["type"] for plugin in plugins] != ["bridge", "portmap", "firewall", "tuning"] or
            plugins[2] != {"type": "firewall", "backend": "iptables", "ingressPolicy": "same-bridge"}):
        raise ValueError("relay CNI configuration lacks the validated bridge isolation")
    bridge = plugins[0]
    if bridge["ipam"]["type"] != "host-local":
        raise ValueError("unsupported relay IP allocation")
    if internal:
        bridge.update(isGateway=False, isDefaultGateway=False, ipMasq=False)
        bridge["ipam"]["routes"] = []
        for group in bridge["ipam"]["ranges"]:
            for subnet in group:
                subnet.pop("gateway", None)
    # Attachment-local tuning avoids DEL undoing another interface's policy.
    plugins[3]["sysctl"] = {"net.ipv6.conf.IFNAME.disable_ipv6": "1"}
    if public_service:
        policy = (Path('/usr/local/share/codex-sandbox/network-policy.json')).read_bytes()
        plugins.append({"type": "public-only", "policyDigest": hashlib.sha256(policy).hexdigest()})
    return config


def main():
    name, kind, owner, *boundary = sys.argv[1:]
    domain, role = boundary if boundary else ("-", "-")
    if not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise ValueError("invalid relay owner")
    relay_name = re.fullmatch(r"codex-(?:agent-podman|host-editor)-(?:link|egress)-[0-9]+-[0-9a-f]{12}", name)
    service_name = re.fullmatch(r"[a-zA-Z0-9_.-]+-(?:zulip-public-only|application|refresh)", name)
    if not relay_name and not service_name:
        raise ValueError("network name is not owned by a sandbox service")
    if ((kind not in ("internal", "egress") or ("-link-" in name) != (kind == "internal"))
            if relay_name else kind != "public-service"):
        raise ValueError("network purpose differs from its name")
    destination = Path.home() / ".config/cni/net.d/default" / f"nerdctl-{name}.conflist"
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to adopt an existing relay network")
    # The caller owns this unique name before entry and must clean up even if
    # creation succeeds but configuration or transport subsequently fails.
    labels = (["--label", "dev.codex.service-owner=" + owner,
               "--label", "dev.codex.public-policy=sha256:" + hashlib.sha256(
                   Path('/usr/local/share/codex-sandbox/network-policy.json').read_bytes()).hexdigest(),
               *([] if domain == "-" else ["--label", "dev.codex.credential-domain=" + domain]),
               *([] if role == "-" else ["--label", "dev.codex.network-role=" + role])]
              if kind == "public-service" else ["--label", "dev.codex.relay-owner=" + owner])
    subprocess.run(["nerdctl", "--namespace", "default", "network", "create",
                    *labels, name], check=True, timeout=30)
    config = configure(json.loads(destination.read_text()), kind == "internal",
                       kind == "public-service")
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent)
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
