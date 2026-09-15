"""Own the common Caddy/profile-helper topology for authenticated egress."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Callable

from caddy_foundation import CaddyImageIdentity, publish_configuration


@dataclass(frozen=True)
class EgressPairPlan:
    domain: str
    service_owner: str
    caddy_name: str
    helper_name: str
    socket_volume: str
    configuration_path: Path
    configuration: bytes
    caddy_image: CaddyImageIdentity
    helper_image: str
    uid: int
    gid: int
    application_network: str
    helper_network: str
    public_networks: tuple[tuple[str, str, str], ...]
    helper_mounts: tuple[str, ...]
    helper_environment: tuple[str, ...]
    helper_arguments: tuple[str, ...]
    runtime_flags: tuple[str, ...] = ()
    extra_caddy_networks: tuple[str, ...] = ()

    def implementation_identity(self, helper_identity: str) -> str:
        material = {
            "caddy": self.caddy_image.__dict__,
            "configuration": "sha256:" + hashlib.sha256(self.configuration).hexdigest(),
            "helper": helper_identity,
        }
        return "sha256:" + hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()


def start_egress_pair(
    runtime,
    plan: EgressPairPlan,
    effect: Callable[[str, Callable[[], object]], object],
    *,
    cancelled: Callable[[], bool] = lambda: False,
    error: Callable[[str], Exception] = RuntimeError,
    logs: Callable[[str], str] | None = None,
) -> None:
    """Create one pair in dependency order while its caller records each effect."""
    def check_cancelled() -> None:
        if cancelled():
            raise error(f"{plan.domain} authenticated egress startup cancelled")

    check_cancelled()
    effect("configuration", lambda: publish_configuration(
        plan.configuration_path, plan.configuration))
    check_cancelled()
    effect("socket-volume", lambda: runtime.create_owned_volume(
        plan.socket_volume, plan.uid, plan.gid, plan.service_owner,
        plan.domain, "profile-socket"))
    check_cancelled()
    for status, role, network in plan.public_networks:
        effect(status, lambda role=role, network=network: runtime.create_public_service_network(
            network, plan.service_owner, domain=plan.domain, role=role))
        check_cancelled()

    common = [
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
        "--user", f"{plan.uid}:{plan.gid}", "--pids-limit", "64",
        "--memory", "256m", "--cpus", "1", "--ulimit", "nofile=256:256",
        "--label", f"dev.codex.service-owner={plan.service_owner}",
        "--label", f"dev.codex.credential-domain={plan.domain}",
    ]
    helper = [
        "run", "--detach", "--name", plan.helper_name, *common,
        "--label", f"dev.codex.service-role={plan.domain}-profile-helper",
        "--network", plan.helper_network, *plan.runtime_flags,
        "--mount", f"type=volume,src={plan.socket_volume},dst=/run/profile-helper",
    ]
    for mount in plan.helper_mounts:
        helper += ["--mount", mount]
    for value in plan.helper_environment:
        helper += ["--env", value]
    helper += ["--entrypoint", "/trusted/bin/profile-helper", plan.helper_image,
               *plan.helper_arguments]
    effect("helper-container", lambda: runtime.run(helper, stdout=subprocess.DEVNULL))
    check_cancelled()

    caddy = [
        "run", "--detach", "--name", plan.caddy_name, *common,
        "--label", f"dev.codex.service-role={plan.domain}-caddy",
        "--cap-add=NET_BIND_SERVICE", "--network", plan.application_network, *plan.runtime_flags,
        "--mount", f"type=volume,src={plan.socket_volume},dst=/run/profile-helper,readonly",
        "--mount", f"type=bind,src={plan.configuration_path},dst=/etc/caddy/caddy.json,readonly",
        plan.caddy_image.runtime_reference, "caddy", "run", "--config", "/etc/caddy/caddy.json",
    ]
    effect("caddy-container", lambda: runtime.run(caddy, stdout=subprocess.DEVNULL))
    for network in plan.extra_caddy_networks:
        check_cancelled()
        effect("caddy-attachment", lambda network=network: runtime.run(
            ["network", "connect", network, plan.caddy_name], stdout=subprocess.DEVNULL))

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        check_cancelled()
        ready = runtime.run([
            "exec", plan.caddy_name, "wget", "-q", "-O", "/dev/null",
            "http://127.0.0.1:8787/ready",
        ], check=False, capture_output=True)
        if ready.returncode == 0:
            return
        time.sleep(.1)
    detail = ""
    if logs is not None:
        output = "\n".join(filter(None, (logs(plan.caddy_name), logs(plan.helper_name))))
        detail = f":\n{output}" if output else ""
    raise error(f"{plan.domain} Caddy/helper pair did not become ready{detail}")
