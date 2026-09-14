"""Codex broker lifecycle identity and schema-3 compatibility record values."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from trusted_services import ServiceFamily, ServicePlan, ServiceScope

STATE_SCHEMA = 1
SESSION_LIFECYCLE_SCHEMA = 1
NETWORK = "codex-public-only"
CREDENTIAL_DOMAIN = "codex"
ENDPOINT_PORT = 8787
MANAGED_FIELDS = {
    "container", "key", "image", "service-owner", "implementation-identity",
    "state-schema", "lifecycle-state", "credential-domain", "network", "network-owner",
    "endpoint", "credential-volume", "token-lifetime", "runtime-owner", "resource-status",
}
LEGACY_FIELDS = {"container", "key", "image"}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
STATES = {"starting", "ready", "published", "failed", "stopping", "cleanup-failed", "removed"}


def adapter_bytes(root: Path) -> bytes:
    return b"\0".join(
        path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "tests" not in path.parts and "__pycache__" not in path.parts
    )


def image_reference(image: str) -> str:
    if "@sha256:" in image:
        return image
    if _DIGEST.fullmatch(image):
        return "codex-broker@" + image
    raise ValueError("Codex broker image is not an immutable digest reference")


def resolved_plan(root: Path, image: str, uid: int, gid: int):
    implementation = adapter_bytes(root)
    plan = ServicePlan(
        role="codex-broker", family=ServiceFamily.AUTHENTICATED_EGRESS,
        scope=ServiceScope.SHARED_SESSION, adapter="codex-broker",
        adapter_identity="sha256:" + hashlib.sha256(implementation).hexdigest(),
        state_schema=STATE_SCHEMA, image_role="broker", image_uid=uid, image_gid=gid,
        fixed_parameters={"credential-domain": CREDENTIAL_DOMAIN, "network": NETWORK,
                          "endpoint": {"port": ENDPOINT_PORT}},
    )
    return plan.resolve(adapter_bytes=implementation, image=image_reference(image))


def credential_source_identity(directory: Path) -> str:
    """Identify the admitted credential view without serializing its path or contents."""
    directory_stat = directory.stat()
    auth_stat = (directory / "auth.json").stat()
    value = {
        "domain": CREDENTIAL_DOMAIN,
        "directory": [directory_stat.st_dev, directory_stat.st_ino, directory_stat.st_uid,
                      directory_stat.st_mode & 0o777],
        "file": [auth_stat.st_dev, auth_stat.st_ino, auth_stat.st_uid, auth_stat.st_mode & 0o777],
    }
    return "sha256:" + hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def parse_auth_record(value: Any, *, managed_required: bool = False) -> tuple[str, Mapping[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("authentication record must be an object")
    fields = set(value)
    if fields == LEGACY_FIELDS:
        if managed_required:
            raise ValueError("managed authentication record cannot downgrade to legacy")
        if not all(isinstance(value[field], str) and value[field] for field in LEGACY_FIELDS):
            raise ValueError("invalid legacy authentication record")
        return "legacy", value
    if fields != MANAGED_FIELDS:
        raise ValueError("invalid managed authentication record fields")
    strings = ("container", "key", "image", "service-owner", "implementation-identity",
               "credential-domain", "network", "token-lifetime")
    if not all(isinstance(value.get(field), str) and value[field] for field in strings):
        raise ValueError("invalid managed authentication record values")
    if (not _TOKEN.fullmatch(value["key"]) or not _OWNER.fullmatch(value["service-owner"]) or
            not _DIGEST.fullmatch(value["implementation-identity"]) or
            value["state-schema"] != STATE_SCHEMA or value["lifecycle-state"] not in STATES or
            value["credential-domain"] != CREDENTIAL_DOMAIN or value["network"] != NETWORK or
            value["token-lifetime"] != "shared-session" or
            value["endpoint"] != {"container": value["container"], "port": ENDPOINT_PORT} or
            value["resource-status"] not in ({"container": "intended"}, {"container": "created"},
                                             {"container": "unknown"}, {"container": "removed"})):
        raise ValueError("invalid managed authentication record")
    volume = value["credential-volume"]
    if (not isinstance(volume, dict) or set(volume) != {"kind", "target", "identity", "lifetime"} or
            volume.get("kind") != "bind" or volume.get("target") != "/var/lib/codex-auth" or
            volume.get("lifetime") != "shared-session" or
            not isinstance(volume.get("identity"), str) or not _DIGEST.fullmatch(volume["identity"])):
        raise ValueError("invalid managed credential volume")
    runtime = value["runtime-owner"]
    if not isinstance(runtime, dict) or not isinstance(runtime.get("provider"), str):
        raise ValueError("invalid managed runtime owner")
    if value["network-owner"] != {"kind": "admitted-runtime-public-egress", "runtime": runtime}:
        raise ValueError("invalid managed network owner")
    return "managed", value
