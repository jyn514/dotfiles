"""Trusted-service lifecycle values, transitions, and resource ownership.

This module contains no container commands, credentials, protocol fields, host
paths, or resolver supervision. Adapters translate those details into opaque,
owner-validating resource and endpoint values.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
import hashlib
from graphlib import CycleError, TopologicalSorter
import json
import re
import time
from threading import Lock
from types import MappingProxyType
from typing import Any, Callable, Mapping


_ROLE = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_RESOURCE = re.compile(r"[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_RESOLUTION_KEY = object()


class LifecycleError(ValueError):
    """A value or operation violates the trusted-service contract."""


class ServiceFamily(str, Enum):
    COMMAND_PROXY = "command-proxy"
    AUTHENTICATED_EGRESS = "authenticated-egress"
    HOST_RELAY = "host-relay"


class ServiceScope(str, Enum):
    SHARED_SESSION = "shared-session"
    AGENT_LAUNCH = "agent-launch"


class Availability(str, Enum):
    REQUIRED = "required"
    BEST_EFFORT = "best-effort"


class LifecycleState(str, Enum):
    PLANNED = "planned"
    RESOLVED = "resolved"
    PREPARING = "preparing"
    STARTING = "starting"
    READY = "ready"
    PUBLISHED = "published"
    ATTACHED = "attached"
    FAILED = "failed"
    STOPPING = "stopping"
    CLEANUP_FAILED = "cleanup-failed"
    REMOVED = "removed"


class ResourcePresence(str, Enum):
    ABSENT = "absent"
    OWNED = "owned"
    MISMATCHED = "mismatched"


@dataclass(frozen=True)
class ServicePlan:
    role: str
    family: ServiceFamily
    scope: ServiceScope
    adapter: str
    adapter_identity: str
    state_schema: int
    fixed_parameters: Mapping[str, Any] = field(default_factory=dict)
    endpoint_kinds: tuple[str, ...] = ()
    availability: Availability | None = None
    image_role: str | None = None
    image_uid: int | None = None
    image_gid: int | None = None

    def __post_init__(self) -> None:
        _require_role(self.role, "service role")
        _require_role(self.adapter, "adapter")
        _require_digest(self.adapter_identity, "adapter identity")
        if not isinstance(self.family, ServiceFamily):
            raise LifecycleError("service family must be canonical")
        if not isinstance(self.scope, ServiceScope):
            raise LifecycleError("service scope must be canonical")
        if self.availability is not None and not isinstance(self.availability, Availability):
            raise LifecycleError("service availability must be canonical")
        _require_positive_int(self.state_schema, "state schema")
        if self.scope is ServiceScope.SHARED_SESSION:
            if self.availability not in (None, Availability.REQUIRED):
                raise LifecycleError("shared services are always required")
        elif self.availability is None:
            raise LifecycleError("agent-launch services require availability")
        if not isinstance(self.endpoint_kinds, tuple):
            raise LifecycleError("endpoint kinds must be a tuple")
        if len(set(self.endpoint_kinds)) != len(self.endpoint_kinds):
            raise LifecycleError("endpoint kinds must be unique")
        for endpoint in self.endpoint_kinds:
            _require_role(endpoint, "endpoint kind")
        if self.image_role is not None:
            _require_role(self.image_role, "image role")
        if (self.image_uid is None) != (self.image_gid is None):
            raise LifecycleError("image UID and GID must be specified together")
        for value, name in ((self.image_uid, "image UID"), (self.image_gid, "image GID")):
            if value is not None:
                _require_nonnegative_int(value, name)
        if self.image_uid is not None and self.image_role is None:
            raise LifecycleError("image-bound UID/GID require an image role")
        object.__setattr__(self, "fixed_parameters", _freeze_object(self.fixed_parameters,
                                                                    "fixed parameters"))

    def resolve(self, *, adapter_bytes: bytes, image: str | None = None) -> "ResolvedServicePlan":
        if not isinstance(adapter_bytes, bytes):
            raise LifecycleError("adapter bytes must be bytes")
        if self.image_role is None:
            if image is not None:
                raise LifecycleError("host service cannot resolve a container image")
        elif not isinstance(image, str) or _IMAGE.fullmatch(image) is None:
            raise LifecycleError("resolved image must be an immutable digest reference")
        material = {
            "adapter_bytes_sha256": hashlib.sha256(adapter_bytes).hexdigest(),
            "adapter_identity": self.adapter_identity,
            "fixed_parameters": _thaw(self.fixed_parameters),
            "image": image,
            "image_uid": self.image_uid,
            "image_gid": self.image_gid,
        }
        identity = "sha256:" + hashlib.sha256(_canonical_json(material)).hexdigest()
        return ResolvedServicePlan(self, image, identity, _RESOLUTION_KEY)


@dataclass(frozen=True)
class ResolvedServicePlan:
    plan: ServicePlan
    image: str | None
    implementation_identity: str
    _resolution_key: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._resolution_key is not _RESOLUTION_KEY:
            raise LifecycleError("resolved plans must be created by ServicePlan.resolve")
        if not isinstance(self.plan, ServicePlan):
            raise LifecycleError("resolved plan must contain a service plan")
        if (self.plan.image_role is None) != (self.image is None):
            raise LifecycleError("resolved image does not match service plan")
        if self.image is not None and _IMAGE.fullmatch(self.image) is None:
            raise LifecycleError("resolved image must be an immutable digest reference")
        _require_digest(self.implementation_identity, "implementation identity")


@dataclass(frozen=True)
class EndpointRecord:
    kind: str
    identity: str
    transport: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_role(self.kind, "endpoint kind")
        _require_owner(self.identity, "endpoint identity")
        object.__setattr__(self, "transport", _freeze_object(self.transport, "endpoint transport"))

    def to_mapping(self) -> dict[str, Any]:
        return {"kind": self.kind, "identity": self.identity, "transport": _thaw(self.transport)}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EndpointRecord":
        _require_keys(value, {"kind", "identity", "transport"}, "endpoint record")
        return cls(value["kind"], value["identity"], value["transport"])


@dataclass(frozen=True)
class SharedServiceRecord:
    role: str
    family: ServiceFamily
    implementation_identity: str
    state_schema: int
    runtime_owner: str
    recovery_identity: str
    endpoints: tuple[EndpointRecord, ...]
    session_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_role(self.role, "service role")
        if not isinstance(self.family, ServiceFamily):
            raise LifecycleError("service family must be canonical")
        _require_digest(self.implementation_identity, "implementation identity")
        _require_positive_int(self.state_schema, "state schema")
        _require_owner(self.runtime_owner, "runtime owner")
        _require_owner(self.recovery_identity, "recovery identity")
        if not isinstance(self.endpoints, tuple) or not all(
                isinstance(endpoint, EndpointRecord) for endpoint in self.endpoints):
            raise LifecycleError("service endpoints must be endpoint records")
        if len({endpoint.kind for endpoint in self.endpoints}) != len(self.endpoints):
            raise LifecycleError("service endpoint kinds must be unique")
        if self.session_token is not None and (
                not isinstance(self.session_token, str) or not self.session_token):
            raise LifecycleError("session token must be a non-empty string when present")

    def to_mapping(self) -> dict[str, Any]:
        value = {
            "family": self.family.value,
            "implementation_identity": self.implementation_identity,
            "state_schema": self.state_schema,
            "runtime_owner": self.runtime_owner,
            "recovery_identity": self.recovery_identity,
            "endpoints": [endpoint.to_mapping() for endpoint in self.endpoints],
        }
        if self.session_token is not None:
            value["session_token"] = self.session_token
        return value

    @classmethod
    def from_mapping(cls, role: str, value: Mapping[str, Any]) -> "SharedServiceRecord":
        required = {"family", "implementation_identity", "state_schema", "runtime_owner",
                    "recovery_identity", "endpoints"}
        _require_keys(value, required, "shared service record", {"session_token"})
        if not isinstance(value["endpoints"], list):
            raise LifecycleError("service endpoints must be an array")
        try:
            family = ServiceFamily(value["family"])
            endpoints = tuple(EndpointRecord.from_mapping(item) for item in value["endpoints"])
            return cls(role, family, value["implementation_identity"], value["state_schema"],
                       value["runtime_owner"], value["recovery_identity"], endpoints,
                       value.get("session_token"))
        except LifecycleError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise LifecycleError("malformed shared service record") from error


@dataclass(frozen=True)
class EndpointAuthorization:
    owner: str
    endpoint_identities: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_owner(self.owner, "authorization owner")
        if not isinstance(self.endpoint_identities, tuple) or not self.endpoint_identities:
            raise LifecycleError("authorization requires endpoint identities")
        for identity in self.endpoint_identities:
            _require_owner(identity, "authorized endpoint identity")


class OwnerSet:
    """Reject reuse of a service-instance owner, including after removal."""

    def __init__(self) -> None:
        self._owners: set[str] = set()
        self._lock = Lock()

    def claim(self, owner: str) -> None:
        _require_owner(owner, "resource owner")
        with self._lock:
            if owner in self._owners:
                raise LifecycleError(f"resource owner already used: {owner}")
            self._owners.add(owner)


@dataclass(frozen=True)
class OwnedResource:
    identity: str
    owner: str
    inspect: Callable[[], ResourcePresence]
    remove: Callable[[], None]
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_resource(self.identity)
        _require_owner(self.owner, "resource owner")
        if not callable(self.inspect) or not callable(self.remove):
            raise LifecycleError("resource inspection and removal must be callable")
        if not isinstance(self.depends_on, tuple):
            raise LifecycleError("resource dependencies must be a tuple")
        for identity in self.depends_on:
            _require_resource(identity)


@dataclass(frozen=True)
class CleanupFailure:
    identity: str
    code: str


@dataclass(frozen=True)
class CleanupResult:
    primary_status: int
    failures: tuple[CleanupFailure, ...]
    remaining: tuple[str, ...]


class ResourceRegistry:
    """Serialize cleanup and retain failed branches for owner-validated recovery."""

    RETRY_DELAYS = (0.05,) * 19

    def __init__(self, owner: str) -> None:
        _require_owner(owner, "resource owner")
        self.owner = owner
        self._resources: dict[str, OwnedResource] = {}
        self._started = False
        self._lock = Lock()
        self._cleanup_lock = Lock()

    def register(self, resource: OwnedResource) -> None:
        if not isinstance(resource, OwnedResource):
            raise LifecycleError("resource must be an owned resource")
        with self._lock:
            if self._started:
                raise LifecycleError("resource cleanup has started")
            if resource.owner != self.owner:
                raise LifecycleError("resource owner does not match registry owner")
            if resource.identity in self._resources:
                raise LifecycleError(f"resource already registered: {resource.identity}")
            missing = set(resource.depends_on) - self._resources.keys()
            if missing:
                raise LifecycleError(f"resource dependencies are not registered: {sorted(missing)!r}")
            self._resources[resource.identity] = resource

    @property
    def identities(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._resources)

    def cleanup(self, primary_status: int) -> CleanupResult:
        with self._cleanup_lock:
            with self._lock:
                self._started = True
            result = self._cleanup_once(primary_status)
            for delay in self.RETRY_DELAYS:
                if not result.remaining or (result.failures and all(
                        failure.code == "resource-owner-mismatch"
                        for failure in result.failures)):
                    break
                time.sleep(delay)
                result = self._cleanup_once(primary_status)
            return result

    def _cleanup_once(self, primary_status: int) -> CleanupResult:
        failures: list[CleanupFailure] = []
        with self._lock:
            resources = dict(self._resources)
        sorter = _removal_graph(resources)
        try:
            sorter.prepare()
        except CycleError as error:
            raise LifecycleError("resource dependency cycle") from error
        while sorter.is_active():
            ready = sorter.get_ready()
            if not ready:
                break
            wave = [resources[identity] for identity in ready]
            completed: list[str] = []
            with ThreadPoolExecutor(max_workers=len(wave)) as workers:
                results = [(resource, workers.submit(self._remove_owned, resource))
                           for resource in wave]
                for resource, future in results:
                    try:
                        future.result()
                    except Exception as error:
                        failures.append(CleanupFailure(resource.identity,
                                                       _safe_error_code(error)))
                    else:
                        completed.append(resource.identity)
                        with self._lock:
                            self._resources.pop(resource.identity, None)
            if completed:
                sorter.done(*completed)
        with self._lock:
            remaining = _removal_order(self._resources)
        return CleanupResult(primary_status, tuple(failures), remaining)

    @staticmethod
    def _remove_owned(resource: OwnedResource) -> None:
        presence = resource.inspect()
        if not isinstance(presence, ResourcePresence):
            raise LifecycleError("resource inspection returned an invalid result")
        if presence is ResourcePresence.MISMATCHED:
            raise LifecycleError("resource-owner-mismatch")
        if presence is ResourcePresence.OWNED:
            try:
                resource.remove()
            except Exception as error:
                # Engines can complete removal but lose or reject the response.
                # Absence is the desired state and makes cleanup safe to retry.
                presence = resource.inspect()
                if not isinstance(presence, ResourcePresence):
                    raise LifecycleError("resource inspection returned an invalid result") from error
                if presence is ResourcePresence.ABSENT:
                    return
                if presence is ResourcePresence.MISMATCHED:
                    raise LifecycleError("resource-owner-mismatch") from error
                raise


class ServiceLifecycle:
    def __init__(self, resolved: ResolvedServicePlan, owner: str, owners: OwnerSet) -> None:
        if not isinstance(resolved, ResolvedServicePlan):
            raise LifecycleError("lifecycle requires a resolved service plan")
        if not isinstance(owners, OwnerSet):
            raise LifecycleError("lifecycle requires an owner set")
        owners.claim(owner)
        self.resolved = resolved
        self.owner = owner
        self.state = LifecycleState.PLANNED
        self.authorization: EndpointAuthorization | None = None
        self.was_attached = False

    def transition(self, target: LifecycleState,
                   *, authorization: EndpointAuthorization | None = None) -> None:
        if not isinstance(target, LifecycleState):
            raise LifecycleError("target lifecycle state must be canonical")
        prospective = self.authorization if authorization is None else authorization
        if prospective is not None:
            if not isinstance(prospective, EndpointAuthorization):
                raise LifecycleError("endpoint authorization must be canonical")
            if prospective.owner != self.owner:
                raise LifecycleError("endpoint authorization owner mismatch")
        allowed = _allowed_transitions(self.resolved.plan, self.state,
                                       prospective is not None, self.was_attached)
        if target not in allowed:
            raise LifecycleError(f"invalid lifecycle transition: {self.state.value} -> {target.value}")
        self.authorization = prospective
        if target is LifecycleState.ATTACHED:
            self.was_attached = True
        self.state = target


def _allowed_transitions(plan: ServicePlan, state: LifecycleState, authorized: bool,
                         was_attached: bool) -> frozenset[LifecycleState]:
    failure_sources = {LifecycleState.PLANNED, LifecycleState.RESOLVED,
                       LifecycleState.PREPARING, LifecycleState.STARTING,
                       LifecycleState.READY, LifecycleState.ATTACHED}
    allowed: set[LifecycleState] = set()
    if state is LifecycleState.PLANNED:
        allowed.add(LifecycleState.RESOLVED)
    elif state is LifecycleState.RESOLVED:
        allowed.add(LifecycleState.PREPARING)
    elif state is LifecycleState.PREPARING:
        allowed.add(LifecycleState.STARTING)
    elif state is LifecycleState.STARTING:
        allowed.add(LifecycleState.READY)
        if (plan.scope is ServiceScope.AGENT_LAUNCH
                and plan.availability is Availability.BEST_EFFORT and authorized):
            allowed.add(LifecycleState.ATTACHED)
    elif state is LifecycleState.READY:
        if plan.scope is ServiceScope.SHARED_SESSION:
            allowed.add(LifecycleState.PUBLISHED)
        elif was_attached:
            allowed.add(LifecycleState.STOPPING)
        else:
            allowed.add(LifecycleState.ATTACHED)
    elif state is LifecycleState.ATTACHED:
        allowed.add(LifecycleState.STOPPING)
        if plan.availability is Availability.BEST_EFFORT:
            allowed.add(LifecycleState.READY)
    elif state in (LifecycleState.PUBLISHED, LifecycleState.FAILED):
        allowed.add(LifecycleState.STOPPING)
    elif state is LifecycleState.STOPPING:
        allowed.update((LifecycleState.REMOVED, LifecycleState.CLEANUP_FAILED))
    elif state is LifecycleState.CLEANUP_FAILED:
        allowed.add(LifecycleState.STOPPING)
    if state in failure_sources:
        allowed.add(LifecycleState.FAILED)
    return frozenset(allowed)


def _removal_order(resources: Mapping[str, OwnedResource]) -> tuple[str, ...]:
    try:
        return tuple(_removal_graph(resources).static_order())
    except CycleError as error:
        raise LifecycleError("resource dependency cycle") from error


def _removal_graph(resources: Mapping[str, OwnedResource]) -> TopologicalSorter:
    predecessors = {identity: set() for identity in resources}
    for resource in resources.values():
        for dependency in resource.depends_on:
            if dependency in predecessors:
                predecessors[dependency].add(resource.identity)
    return TopologicalSorter(predecessors)


def _freeze_object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleError(f"{name} must be an object")
    return _freeze_json(value, name)


def _freeze_json(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise LifecycleError(f"{name} must contain finite JSON values")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise LifecycleError(f"{name} keys must be strings")
        return MappingProxyType({key: _freeze_json(item, name) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, name) for item in value)
    raise LifecycleError(f"{name} must contain JSON values")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise LifecycleError("value is not canonical JSON data") from error


def _require_keys(value: Mapping[str, Any], required: set[str], name: str,
                  optional: set[str] | None = None) -> None:
    if not isinstance(value, Mapping):
        raise LifecycleError(f"{name} must be an object")
    keys = set(value)
    allowed = required | (optional or set())
    if not required <= keys <= allowed:
        raise LifecycleError(f"{name} has invalid fields")


def _require_role(value: Any, name: str) -> None:
    if not isinstance(value, str) or _ROLE.fullmatch(value) is None:
        raise LifecycleError(f"{name} is not canonical")


def _require_digest(value: Any, name: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise LifecycleError(f"{name} must be a sha256 identity")


def _require_owner(value: Any, name: str) -> None:
    if not isinstance(value, str) or _OWNER.fullmatch(value) is None:
        raise LifecycleError(f"{name} is not canonical")


def _require_resource(value: Any) -> None:
    if not isinstance(value, str) or _RESOURCE.fullmatch(value) is None:
        raise LifecycleError("resource identity is not canonical")


def _require_positive_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError(f"{name} must be a positive integer")


def _require_nonnegative_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError(f"{name} must be a non-negative integer")


def _safe_error_code(error: BaseException) -> str:
    """Return an allowlisted diagnostic code without serializing exception data."""
    if isinstance(error, LifecycleError) and str(error) == "resource-owner-mismatch":
        return "resource-owner-mismatch"
    return "removal-failed:" + type(error).__name__
