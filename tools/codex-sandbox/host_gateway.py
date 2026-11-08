"""Host ownership of one launch's gateway; gateway.py owns its container supervisor.

Import this module from the sandbox tool directory; it has no CLI dispatcher.
The launcher retains scheduling and must retain the handle before prepare/start,
join its workers before cleanup, and persist remaining resources before discarding
scratch state. This owner binds one admitted runtime and resource plan for life.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING
import uuid

from host_tcp_bridge import FixedTcpBridge
from relay_lifecycle import RelayResourcePlan
from sandbox_runtime import (
    ContainerRuntime, VMRuntime, ResourceKind, ResourceOwnerAuthority,
    remove_owned_resource, resource_presence, runtime_identity,
)
from trusted_services import (
    CleanupResult, LifecycleError, OwnedResource, ResourcePresence, ResourceRegistry, service_timing,
)

if TYPE_CHECKING:
    from tic_broker import TicBrokerLaunch


class GatewayError(Exception):
    pass


@dataclass(frozen=True)
class BuildSshProjection:
    user: str
    port: int
    key: Path
    known_hosts: Path
    guest_key: str
    guest_known_hosts: str


@dataclass(frozen=True)
class GatewayPreparation:
    """Guest projection and availability after successful preparation."""

    arguments: tuple[str, ...]
    selected: bool
    build_available: bool


def create_relay_network(runtime: ContainerRuntime, name: str, *, internal: bool,
                         owner: str) -> None:
    if isinstance(runtime, VMRuntime):
        runtime.create_relay_network(name, internal=internal, owner=owner)
    else:
        runtime.run(["network", "create", *(["--internal"] if internal else []),
                     "--label", f"dev.codex.service-owner={owner}",
                     "--opt", "isolate=true", name],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


def create_relay_networks(runtime: ContainerRuntime, networks: tuple[tuple[str, bool], ...],
                          *, owner: str) -> None:
    if isinstance(runtime, VMRuntime):
        runtime.create_relay_networks(networks, owner=owner)
    else:
        for name, internal in networks:
            create_relay_network(runtime, name, internal=internal, owner=owner)


def gateway_network_presence(runtime: ContainerRuntime, name: str, owner: str) -> ResourcePresence:
    return resource_presence(
        runtime, ResourceKind.NETWORK, name, owner,
        authority=ResourceOwnerAuthority.RELAY,
    )


def gateway_container_presence(runtime: ContainerRuntime, name: str, owner: str) -> ResourcePresence:
    return resource_presence(runtime, ResourceKind.CONTAINER, name, owner)


def _relay_recovery_directory(home: Path) -> Path:
    return home / ".local/state/codex-sandbox/gateway-recovery"


def _relay_recovery_dirfd(home: Path, *, create: bool) -> int | None:
    """Open the private recovery directory without following any path component."""
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(home, flags)
    try:
        for component in (".local", "state", "codex-sandbox", "gateway-recovery"):
            try:
                child = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    return None
                os.mkdir(component, 0o700, dir_fd=fd)
                child = os.open(component, flags, dir_fd=fd)
            status = os.fstat(child)
            if (not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid()
                    or (component == "gateway-recovery"
                        and stat.S_IMODE(status.st_mode) != 0o700)):
                os.close(child)
                raise GatewayError("gateway recovery path is not a private directory")
            os.close(fd)
            fd = child
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def persist_relay_recovery(runtime: ContainerRuntime, home: Path,
                           plan: RelayResourcePlan, owner: str,
                           remaining: tuple[str, ...]) -> Path | None:
    resources = plan.recovery_resources(remaining, owner)
    if not resources:
        return None
    directory = _relay_recovery_directory(home)
    dirfd = _relay_recovery_dirfd(home, create=True)
    assert dirfd is not None
    name = f"{owner}.json"
    temporary = f".{owner}.{secrets.token_hex(8)}.tmp"
    payload = {"version": 1, "runtime": runtime_identity(runtime),
               "owner": owner, "resources": resources}
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=dirfd)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.rename(temporary, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        os.fsync(dirfd)
    finally:
        try:
            os.unlink(temporary, dir_fd=dirfd)
        except FileNotFoundError:
            pass
        os.close(dirfd)
    return directory / name


def parse_relay_recovery(runtime: ContainerRuntime, data: bytes) -> tuple[str, list[dict[str, object]]]:
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {"version", "runtime", "owner", "resources"}
            or isinstance(value.get("version"), bool) or value.get("version") != 1
            or value.get("runtime") != runtime_identity(runtime)
            or not isinstance(value.get("owner"), str)
            or not isinstance(value.get("resources"), list) or len(value["resources"]) > 4):
        raise GatewayError("invalid gateway recovery record")
    owner = value["owner"]
    parsed: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for item in value["resources"]:
        if (not isinstance(item, dict) or set(item) != {"kind", "name", "owner", "dependencies"}
                or item.get("owner") != owner or item.get("kind") not in {"network", "container"}
                or not isinstance(item.get("name"), str) or not item["name"]
                or not isinstance(item.get("dependencies"), list)
                or any(not isinstance(dependency, str) or not dependency
                       for dependency in item["dependencies"])
                or len(set(item["dependencies"])) != len(item["dependencies"])):
            raise GatewayError("invalid gateway recovery resource")
        identity = (item["kind"], item["name"])
        if identity in identities:
            raise GatewayError("duplicate gateway recovery resource")
        identities.add(identity)
        parsed.append(item)
    for item in parsed:
        if item["kind"] == "network" and item["dependencies"]:
            raise GatewayError("network recovery resource has dependencies")
        if any(("network", dependency) not in identities for dependency in item["dependencies"]):
            raise GatewayError("missing gateway recovery dependency")
    return owner, parsed


def recover_relays(runtime: ContainerRuntime, home: Path) -> None:
    try:
        dirfd = _relay_recovery_dirfd(home, create=False)
    except (OSError, GatewayError) as error:
        print(f"warning: gateway recovery directory retained: {error}", file=sys.stderr)
        return
    if dirfd is None:
        return
    try:
        names = sorted(name for name in os.listdir(dirfd) if name.endswith(".json"))[:64]
        for name in names:
            try:
                descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dirfd)
                with os.fdopen(descriptor, "rb") as source:
                    status = os.fstat(source.fileno())
                    if (not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid()
                            or stat.S_IMODE(status.st_mode) != 0o600 or status.st_size > 16384):
                        raise GatewayError("gateway recovery record is not a private regular file")
                    owner, resources = parse_relay_recovery(runtime, source.read(16385))
                registry = ResourceRegistry(owner)
                for item in sorted(resources, key=lambda item: item["kind"] == "container"):
                    name_value = item["name"]
                    dependencies = tuple(f"network:{dependency}" for dependency in item["dependencies"])
                    if item["kind"] == "network":
                        registry.register(OwnedResource(
                            f"network:{name_value}", owner,
                            lambda name_value=name_value: gateway_network_presence(runtime, name_value, owner),
                            lambda name_value=name_value: remove_owned_resource(
                                runtime, ResourceKind.NETWORK, name_value, owner,
                                authority=ResourceOwnerAuthority.RELAY)))
                    else:
                        registry.register(OwnedResource(
                            f"container:{name_value}", owner,
                            lambda name_value=name_value: gateway_container_presence(runtime, name_value, owner),
                            lambda name_value=name_value: remove_owned_resource(
                                runtime, ResourceKind.CONTAINER, name_value, owner), dependencies))
                if registry.cleanup(0).remaining:
                    raise GatewayError("gateway resources retained")
            except (OSError, TypeError, ValueError, json.JSONDecodeError,
                    LifecycleError, GatewayError) as error:
                print(f"warning: gateway recovery retained {name}: {error}", file=sys.stderr)
            else:
                os.unlink(name, dir_fd=dirfd)
                os.fsync(dirfd)
    finally:
        os.close(dirfd)


class GatewayHandle:
    """Sole owner of one launch's staged, best-effort gateway resources."""

    def __init__(self, runtime: ContainerRuntime, resources: RelayResourcePlan) -> None:
        self.runtime = runtime
        self.owner = uuid.uuid4().hex
        self.registry = ResourceRegistry(self.owner)
        self.resources = resources
        self.cancelled = threading.Event()
        self.build_bridge: FixedTcpBridge | None = None
        # Selected reachable SSH endpoint, independent of optional bridge ownership.
        self.build_port: int | None = None
        self.build_unavailable = False
        # Its lifecycle remains registered with the broker, not this gateway.
        self.tic_bridge: FixedTcpBridge | None = None
        self.addresses: dict[str, str] = {}
        self.started = False
        self._logical: set[str] = set()
        self.created: set[str] = set()

    def presence(self, identity: str, inspect: Callable[[], ResourcePresence]) -> ResourcePresence:
        return ResourcePresence.OWNED if identity in self.created else inspect()

    def _register_logical(self, identity: str, *, depends_on: tuple[str, ...] = (),
                          remove: Callable[[], None] = lambda: None) -> None:
        self._logical.add(identity)
        self.registry.register(OwnedResource(
            identity, self.owner,
            lambda identity=identity: (ResourcePresence.OWNED if identity in self._logical
                                       else ResourcePresence.ABSENT),
            lambda identity=identity, remove=remove: (remove(), self._logical.discard(identity)),
            depends_on,
        ))

    def cleanup(self, primary_status: int = 0) -> CleanupResult:
        self.cancelled.set()
        return self.registry.cleanup(primary_status)

    def prepare(self, capabilities: frozenset[str],
                build: BuildSshProjection | None) -> GatewayPreparation:
        """Prepare once; retain this handle even when resource creation fails.

        A stopped build service is optional and sets build_unavailable even when
        later network creation fails. A selected TicGit listener still prepares
        the shared networks. No container or guest endpoint is published here.
        """
        nested = "nested-containers" in capabilities and build is not None
        tic = "tic" in capabilities
        if not nested and not tic:
            return GatewayPreparation((), False, False)
        if nested:
            assert build is not None
            target = ("127.0.0.1", build.port)
            if not self.runtime.host_loopback_access:
                self.build_bridge = FixedTcpBridge(target)
                self._register_logical("bridge:build", remove=self.build_bridge.stop)
            try:
                if self.build_bridge is None:
                    # Keep the stopped-service check performed by bridge.start(),
                    # without creating another listener on loopback-capable providers.
                    with socket.create_connection(target, timeout=1):
                        pass
                    self.build_port = target[1]
                else:
                    self.build_bridge.start()
                    self.build_port = self.build_bridge.port
            except OSError as error:
                if self.build_bridge is not None:
                    self.build_bridge.stop()
                print(f"warning: nested Docker relay unavailable: {error}; "
                      "run python3 tools/agent-docker/vm.py start on the host, then restart the sandbox",
                      file=sys.stderr)
                self.build_bridge = None
                self.build_unavailable = True
                build = None
                self._logical.discard("bridge:build")
                if not tic:
                    self.cleanup()
                    return GatewayPreparation((), False, False)
        networks = ((self.resources.link_network, True),
                    (self.resources.egress_network, False))
        for name, _internal in networks:
            identity = f"network:{name}"
            self.registry.register(OwnedResource(
                identity, self.owner,
                lambda name=name, identity=identity: self.presence(
                    identity, lambda: gateway_network_presence(self.runtime, name, self.owner)),
                lambda name=name: remove_owned_resource(
                    self.runtime, ResourceKind.NETWORK, name, self.owner,
                    authority=ResourceOwnerAuthority.RELAY),
            ))
        if self.cancelled.is_set():
            raise GatewayError("gateway startup cancelled")
        create_relay_networks(self.runtime, networks, owner=self.owner)
        self.created.update(f"network:{name}" for name, _internal in networks)
        if self.build_port is None:
            return GatewayPreparation((), True, False)
        assert build is not None
        return GatewayPreparation((
            "--network", self.resources.link_network,
            "--env", f"DOCKER_HOST=ssh://{build.user}@{self.resources.container}:2222",
            "--env", f"AGENT_DOCKER_SSHKEY={build.guest_key}",
            "--env", f"AGENT_DOCKER_KNOWN_HOSTS={build.guest_known_hosts}",
            "--mount", f"type=bind,src={build.key},dst={build.guest_key},readonly",
            "--mount", f"type=bind,src={build.known_hosts},dst={build.guest_known_hosts},readonly",
        ), True, True)

    def start(self, *, image: str, network_flags: list[str],
              tic_port: int | None = None, tic_client: Path | None = None) -> None:
        """Start once after prepare and inspect both networks before admission.

        This establishes container ownership and build-bridge peer admission, not
        TicGit listener/application readiness. Failed startup retains resources
        for the launch's joined cleanup; it must not be retried on this handle.
        """
        if self.started:
            raise GatewayError("gateway already started")
        build_port = str(self.build_port) if self.build_port is not None else None
        if build_port is None and tic_port is None:
            raise GatewayError("gateway requires a listener")
        container_resource = f"container:{self.resources.container}"
        self.registry.register(OwnedResource(
            container_resource, self.owner,
            lambda: self.presence(container_resource, lambda: gateway_container_presence(
                self.runtime, self.resources.container, self.owner)),
            lambda: remove_owned_resource(
                self.runtime, ResourceKind.CONTAINER, self.resources.container, self.owner),
            self.resources.bound_topology()[container_resource],
        ))
        if self.cancelled.is_set():
            raise GatewayError("gateway startup cancelled")
        arguments = [
            "--label", f"dev.codex.service-owner={self.owner}",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
            "--network", self.resources.egress_network,
            "--network", self.resources.link_network, *network_flags,
            *([] if isinstance(self.runtime, VMRuntime) else ["--add-host", "host.docker.internal:host-gateway"]),
            *(["--mount", f"type=bind,src={tic_client},dst=/opt/agent-tools/bin/ti,readonly"]
              if tic_client is not None else []),
            "--entrypoint", "/trusted/bin/sandbox-gateway",
        ]
        command = [
            "--host", self.runtime.host_address,
            *(["--build-port", build_port] if build_port is not None else []),
            *(["--tic-port", str(tic_port)] if tic_port is not None else []),
        ]
        if hasattr(self.runtime, 'start_detached'):
            self.runtime.start_detached(image, self.resources.container, arguments, command)
        else:
            self.runtime.run(["run", "--detach", "--name", self.resources.container,
                              *arguments, image, *command],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        self.created.add(container_resource)
        self.started = True
        addresses = self.runtime.network_addresses(
            self.resources.container, (self.resources.link_network, self.resources.egress_network))
        relay_ip = addresses[self.resources.link_network]
        egress_ip = addresses[self.resources.egress_network]
        if not relay_ip or not egress_ip:
            raise GatewayError("gateway has incomplete network addresses")
        self.addresses = {self.resources.link_network: relay_ip,
                          self.resources.egress_network: egress_ip}
        address_resources = []
        for kind, value in (("relay", relay_ip), ("egress", egress_ip)):
            identity = f"address:{kind}-{value.replace('.', '-').replace(':', '-')}"
            self._register_logical(identity, depends_on=(container_resource,))
            address_resources.append(identity)
        if self.cancelled.is_set():
            raise GatewayError("gateway startup cancelled")
        if self.build_bridge is not None:
            self._register_logical("allowlist:build",
                depends_on=("bridge:build", *address_resources))
            self.build_bridge.allow_peers({relay_ip, egress_ip, "127.0.0.1"})
            # Until this allowlist is installed, the bridge rejects every connection.

    def select_tic_upstream(self, broker: TicBrokerLaunch) -> int:
        """Select transport for a ready broker without taking its token/lifetime.

        The broker retains bridge/process registry ownership. The gateway owns route
        choice and peer admission after inspecting both gateway network addresses.
        """
        if self.runtime.host_loopback_access:
            return int(broker.address.rsplit(":", 1)[1])
        with service_timing("tic", "host-bridge"):
            self.tic_bridge = broker.start_bridge(set())
        return self.tic_bridge.port

    def admit_tic_upstream(self) -> None:
        if self.tic_bridge is not None:
            self.tic_bridge.allow_peers(set(self.addresses.values()) | {"127.0.0.1"})

    def wait_tic_ready(self) -> None:
        """Wait only for supervisor listener publication, not application readiness."""
        container = self.resources.container
        from gateway import TIC_READY_MESSAGE
        if hasattr(self.runtime, 'wait_for_log'):
            try:
                self.runtime.wait_for_log(container, TIC_READY_MESSAGE, 7)
            except subprocess.TimeoutExpired as error:
                raise GatewayError('TicGit gateway readiness publication timed out; no fallback') from error
            return
        deadline = time.monotonic() + 7
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GatewayError('TicGit gateway readiness publication timed out; no fallback')
            result = self.runtime.run(
                ['logs', '--tail', '20', container], capture_output=True,
                timeout=min(2, remaining), check=False,
            )
            if result.returncode != 0:
                raise GatewayError('TicGit gateway readiness log is unavailable; no fallback')
            if TIC_READY_MESSAGE in result.stdout.splitlines():
                return
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))


