"""Required per-owning-launch TicGit host child; no shared publication or PID recovery.

The caller supplies accepted host authority, never repository-selected build paths.
Keep this object (and its non-inheritable lifetime writer) in the workload owner,
not an attachment frontend. An external registry composes final-launch cleanup;
calling stop cleans that whole owning registry, so never call it on pane exit.
Final owners must call stop, not just registry.cleanup: failed provider removal
may retain the dependency branch but must never retain host execution authority.
Provider relays may depend on ``process_resource`` and project environment() with
an explicit provider-routable endpoint instead of the loopback broker address.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import subprocess
import stat
import tempfile
import time

from host_tcp_bridge import FixedTcpBridge
from trusted_services import (
    Availability, CleanupFailure, CleanupResult, EndpointAuthorization, LifecycleError, LifecycleState,
    OwnedResource, OwnerSet, ResourcePresence, ResourceRegistry, ServiceFamily,
    ServiceLifecycle, ServicePlan, ServiceScope,
)

POLICY_VERSION = 1
READY_LIMIT = 4096
CONFIG_LIMIT = 64 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_ENDPOINT = re.compile(r"127\.0\.0\.1:([0-9]+)\Z")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleError("duplicate TicGit manifest/readiness field")
        result[key] = value
    return result


def _executable(value: object, digest: object) -> Path:
    if not isinstance(value, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise LifecycleError("invalid installed TicGit executable binding")
    path = Path(value)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise LifecycleError("installed TicGit paths must be canonical and absolute")
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK)
            or metadata.st_uid != os.getuid() or metadata.st_nlink != 1
            or metadata.st_mode & 0o022):
        raise LifecycleError("unsafe installed TicGit executable ownership/mode/link")
    return path


@dataclass(frozen=True)
class InstalledTicBuild:
    broker_executable: Path
    broker_sha256: str
    native_executable: Path
    native_sha256: str
    guest_client_executable: Path
    guest_client_sha256: str
    guest_client_platform: str
    native_revision: str

    @classmethod
    def load(cls, manifest_path: Path) -> "InstalledTicBuild":
        """Derive absolute paths from the single relative bundle manifest."""
        from tic_artifact import protected_bundle
        try:
            if Path(manifest_path).name != 'manifest.json':
                raise ValueError('bundle manifest has a fixed relative name')
            bundle = Path(manifest_path).parent
            _, value, _ = protected_bundle(bundle)
            broker = bundle / value['broker']['path']
            native = bundle / value['native']['path']
            guest = bundle / value['client']['path']
            result = cls(broker, value['broker']['sha256'], native, value['native']['sha256'],
                         guest, value['client']['sha256'], value['client']['platform'], value['native_revision'])
            result.verify()
            return result
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise LifecycleError('invalid TicGit bundle manifest or artifacts') from error

    def verify(self) -> None:
        # The publisher verified artifact bytes. Keep cheap path authority
        # checks here, not repeated detection of host-owned cache corruption.
        if not isinstance(self.native_revision, str) or _REVISION.fullmatch(self.native_revision) is None:
            raise LifecycleError("invalid installed TicGit native revision")
        _executable(str(self.broker_executable), self.broker_sha256)
        _executable(str(self.native_executable), self.native_sha256)
        _executable(str(self.guest_client_executable), self.guest_client_sha256)
        if self.guest_client_platform not in ("linux/amd64", "linux/arm64"):
            raise LifecycleError("TicGit guest client must target a supported Linux platform")


class TicBrokerLaunch:
    def __init__(self, build: InstalledTicBuild, *, workspace: Path, common_dir: Path,
                 user_name: str, user_email: str, namespace: str,
                 owner: str | None = None, owners: OwnerSet | None = None,
                 registry: ResourceRegistry | None = None) -> None:
        build.verify()
        workspace, common_dir = Path(workspace), Path(common_dir)
        for path in (workspace, common_dir):
            if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
                raise LifecycleError("accepted TicGit repository paths must be canonical directories")
        for value in (user_name, user_email, namespace):
            # Native configuration distinguishes a present literal (including
            # empty/whitespace) from absence. Only the inspector owns defaults.
            if not isinstance(value, str) or "\0" in value:
                raise LifecycleError("invalid accepted TicGit identity/namespace")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise LifecycleError("accepted TicGit identity/namespace is not UTF-8 representable") from error
        self.build = build
        self.owner = owner or (registry.owner if registry else secrets.token_hex(16))
        if registry is not None and registry.owner != self.owner:
            raise LifecycleError("TicGit registry owner mismatch")
        self.registry = registry if registry is not None else ResourceRegistry(self.owner)
        self.config = dict(version=1, workspace=str(workspace), common_dir=str(common_dir),
                           native_executable=str(build.native_executable), native_sha256=build.native_sha256,
                           user_name=user_name, user_email=user_email, namespace=namespace)
        adapter_bytes = Path(__file__).read_bytes()
        self.plan = ServicePlan(
            role="tic", family=ServiceFamily.COMMAND_PROXY, scope=ServiceScope.AGENT_LAUNCH,
            adapter="tic-broker", adapter_identity="sha256:" + hashlib.sha256(adapter_bytes).hexdigest(),
            state_schema=1, availability=Availability.BEST_EFFORT, endpoint_kinds=("tic-tcp",),
            fixed_parameters={**self.config, "broker_executable": str(build.broker_executable),
                              "broker_sha256": build.broker_sha256,
                              "native_revision": build.native_revision, "policy_version": POLICY_VERSION,
                              "guest_client_sha256": build.guest_client_sha256,
                              "guest_client_platform": build.guest_client_platform})
        self.lifecycle = ServiceLifecycle(self.plan.resolve(adapter_bytes=adapter_bytes),
                                          self.owner, owners if owners is not None else OwnerSet())
        self.lifecycle.transition(LifecycleState.RESOLVED)
        self.token = ""
        self.address: str | None = None
        self.process: subprocess.Popen | None = None
        self.directory: Path | None = None
        self.lifetime_writer: int | None = None
        self.process_resource = "process:tic-" + secrets.token_hex(16)
        self._resource_suffix = self.process_resource.partition(":")[2]

    def _register(self, kind, inspect, remove, dependencies=()):
        identity = kind + ":" + self._resource_suffix
        try:
            self.registry.register(OwnedResource(identity, self.owner, inspect, remove, dependencies))
        except BaseException:
            # Registration is the transfer point. If the owner rejects it,
            # this adapter still owns the just-created resource locally.
            remove()
            raise
        return identity

    def start(self, *, timeout: float = 10) -> "TicBrokerLaunch":
        if self.lifecycle.state is not LifecycleState.RESOLVED:
            raise LifecycleError("TicGit launch cannot be restarted")
        if not math.isfinite(timeout) or timeout <= 0:
            raise LifecycleError("invalid TicGit readiness deadline")
        self.lifecycle.transition(LifecycleState.PREPARING)
        read_fd = None
        try:
            self.build.verify()
            self.token = secrets.token_hex(32)
            encoded = json.dumps({**self.config, "token": self.token}, ensure_ascii=True).encode("ascii")
            if len(encoded) > CONFIG_LIMIT:
                raise LifecycleError("TicGit private configuration exceeds 64 KiB")
            self.directory = Path(tempfile.mkdtemp(prefix="sandbox-tic-"))
            directory = self.directory
            temp_resource = self._register("temporary", lambda: ResourcePresence.OWNED if directory.exists()
                                           else ResourcePresence.ABSENT,
                                           lambda: shutil.rmtree(directory))
            read_fd, self.lifetime_writer = os.pipe()
            # PEP 446 defaults are intentional and checked, not relaxed globally.
            os.set_inheritable(self.lifetime_writer, False)
            pipe_resource = self._register("pipe", lambda: ResourcePresence.OWNED if self.lifetime_writer is not None
                                           else ResourcePresence.ABSENT, self.close_lifetime, (temp_resource,))
            config_path = directory / "config.json"
            with open(config_path, "xb", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                stream.write(encoded)
            self.lifecycle.transition(LifecycleState.STARTING)
            # Only the bounded readiness line is consumed. Discard diagnostics
            # rather than retaining an unbounded log or a PIPE that can deadlock;
            # startup errors never echo token-bearing configuration.
            self.process = subprocess.Popen(
                [str(self.build.broker_executable), "--config", str(config_path),
                 "--lifetime-fd", str(read_fd)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, pass_fds=(read_fd,),
                close_fds=True, cwd=self.config["workspace"],
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TMPDIR": str(directory)})
            self._register("process", self._process_presence, self._stop_process,
                           (pipe_resource, temp_resource))
            os.close(read_fd)
            read_fd = None
            self.address = self._read_ready(timeout)
            self.lifecycle.transition(LifecycleState.READY)
            return self
        except BaseException:
            if read_fd is not None:
                os.close(read_fd)
            self.lifecycle.transition(LifecycleState.FAILED)
            self.stop(1)
            raise

    def _read_ready(self, timeout: float) -> str:
        assert self.process is not None and self.process.stdout is not None
        stream = self.process.stdout
        deadline = time.monotonic() + timeout
        data = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(stream, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise LifecycleError("TicGit broker readiness deadline exceeded")
                chunk = os.read(stream.fileno(), READY_LIMIT + 1 - len(data))
                if not chunk:
                    raise LifecycleError("TicGit broker exited before readiness")
                data.extend(chunk)
                if len(data) > READY_LIMIT:
                    raise LifecycleError("TicGit readiness line too large")
                if b"\n" in data:
                    if not data.endswith(b"\n") or data.count(b"\n") != 1:
                        raise LifecycleError("invalid TicGit readiness framing")
                    break
        value = json.loads(data, object_pairs_hook=_unique)
        if (not isinstance(value, dict) or set(value) != {"version", "address", "native_revision", "policy_version"}
                or type(value["version"]) is not int or value["version"] != 1
                or value["native_revision"] != self.build.native_revision
                or type(value["policy_version"]) is not int or value["policy_version"] != POLICY_VERSION):
            raise LifecycleError("TicGit readiness build/policy mismatch")
        address = value["address"]
        match = _ENDPOINT.fullmatch(address) if isinstance(address, str) else None
        if match is None or not 1 <= int(match[1]) <= 65535 or self.process.poll() is not None:
            raise LifecycleError("invalid TicGit ready endpoint")
        return address

    def start_bridge(self, peers: set[str]) -> FixedTcpBridge:
        """Optional provider-fixed byte transport; caller still owns guest relay.

        Peer admission is installed before listening; there is no OS-specific
        consent or best-effort mode. Register downstream provider resources with
        a dependency on this bridge's identity (bridge_resource).
        """
        self._require_ready()
        host, port = self.address.rsplit(":", 1)
        bridge = FixedTcpBridge((host, int(port)))
        bridge.allow_peers(peers)
        # Register immediately, including partial start, before another effect.
        self.bridge_resource = self._register(
            "bridge", lambda: ResourcePresence.OWNED, bridge.stop, (self.process_resource,))
        bridge.start()
        return bridge

    def _require_ready(self):
        if self.lifecycle.state not in (LifecycleState.READY, LifecycleState.ATTACHED) or self.process is None or self.process.poll() is not None:
            raise LifecycleError("TicGit broker is not ready")

    def environment(self, endpoint: str | None = None) -> dict[str, str]:
        self._require_ready()
        return {"SANDBOX_TIC_ENDPOINT": endpoint if endpoint is not None else self.address,
                "SANDBOX_TIC_TOKEN": self.token}

    def attach(self) -> None:
        self._require_ready()
        self.lifecycle.transition(LifecycleState.ATTACHED, authorization=EndpointAuthorization(
            self.owner, (self._resource_suffix,)))

    def close_lifetime(self) -> None:
        """Final owning-launch EOF, never attachment exit; no historical PID."""
        if self.lifetime_writer is not None:
            os.close(self.lifetime_writer)
            self.lifetime_writer = None

    def revoke(self) -> None:
        """Revoke admission synchronously before independent teardown can block."""
        self.token = ""
        self.address = None
        self.close_lifetime()

    def _process_presence(self):
        # An exited Popen still owns its pipe descriptors until explicit reap/
        # close; retain it in the registry even after poll reports process exit.
        return ResourcePresence.OWNED if self.process is not None else ResourcePresence.ABSENT

    def _stop_process(self) -> None:
        self.close_lifetime()
        process = self.process
        if process is None:
            return
        try:
            process.wait(timeout=2.5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        self.process = None
        self.token = ""
        self.address = None

    def stop(self, primary_status: int = 0):
        if self.lifecycle.state is LifecycleState.REMOVED:
            return self.registry.cleanup(primary_status)
        if self.lifecycle.state not in (LifecycleState.FAILED, LifecycleState.READY,
                                        LifecycleState.ATTACHED, LifecycleState.CLEANUP_FAILED):
            self.lifecycle.transition(LifecycleState.FAILED)
        if self.lifecycle.state is LifecycleState.READY and not self.lifecycle.was_attached:
            self.lifecycle.transition(LifecycleState.FAILED)
        self.lifecycle.transition(LifecycleState.STOPPING)
        # Admission/lifetime is not a removable provider dependency. A failed
        # container removal deliberately retains its registry predecessors, so
        # delegating this step to the cleanup DAG could leave an authenticated
        # broker and its native child alive after the owning launch has ended.
        self.revoke()
        stop_error = None
        try:
            self._stop_process()
        except Exception as error:
            # Still try every provider cleanup. If the DAG blocks a retry of the
            # process resource, explicitly preserve its bounded failure evidence.
            stop_error = error
        result = self.registry.cleanup(primary_status)
        if (stop_error is not None and self.process is not None
                and not any(failure.identity == self.process_resource for failure in result.failures)):
            result = CleanupResult(result.primary_status, result.failures + (
                CleanupFailure(self.process_resource, "removal-failed:" + type(stop_error).__name__),
            ), result.remaining)
        self.lifecycle.transition(LifecycleState.CLEANUP_FAILED if result.remaining else LifecycleState.REMOVED)
        return result
