#!/usr/bin/env python3
"""Generic sandbox proxy manifest, lifecycle, and host coordination helpers."""

from __future__ import annotations

import argparse
import configparser
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_runtime import (
    ResourceKind, ResourceOwnerAuthority, VMRuntime, ContainerRuntime, image_runtime,
    remove_owned_resource, remove_stopped_sandbox_holders, resource_exists,
    resource_presence, runtime_identity,
    single_json, state_runtime,
)
from trusted_services import (
    LifecycleState, OwnedResource, OwnerSet, ResourcePresence, ResourceRegistry,
    ResourceTopology, ServiceFamily, ServiceLifecycle, ServicePlan, ServiceScope,
)
from codex_broker import (
    PAIR_STATUS_FIELDS, SESSION_LIFECYCLE_SCHEMA, credential_source_identity, parse_auth_record,
    resolved_plan as resolved_codex_broker_plan,
)
from zulip_broker import helper_plan as resolved_zulip_helper_plan, resolved_plan as resolved_zulip_broker_plan
from caddy_foundation import (
    accepted_caddy_image, configuration_digest as caddy_configuration_digest,
    generate_caddy_config, resolve_caddy_image,
    validate_configuration_mount,
)
from authenticated_egress import EgressPairPlan, egress_pair_topology, start_egress_pair
from source_view import check_mount_destinations

OUTER_RUNTIME = ContainerRuntime()
REPOSITORY_METADATA: tuple[Path, tuple[Path, Path]] | None = None


class ConfigError(Exception):
    pass


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BARE_IMAGE_RE = re.compile(r"^[0-9a-f]{64}$")
MODES = {"read-only", "read-write", "hidden"}
COMMAND_FIELDS = {"image-command", "argv", "workdir", "network", "mounts"}
V2_COMMAND_FIELDS = {"image", "argv", "workdir", "network", "mounts"}
CAPABILITY_DEFAULTS = {
    "host-editor": True, "zulip": True,
    "nested-containers": False, "flower-r2": False, "agent-room": False,
}
CAPABILITIES = set(CAPABILITY_DEFAULTS)
RECOVERY_COMMAND = (
    "run `python3 tools/codex-sandbox/sandbox-proxies.py reset --repo <repository>` "
    "after all sandbox sessions exit; reset removes stopped matching agent containers"
)
MOUNT_FIELDS = {"source", "target", "proxy", "agent"}
BUILTIN_MOUNT_FIELDS = {"builtin", "proxy", "agent"}


def _plain_relative(value: Any, label: str, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\0" in value or "\n" in value or "\r" in value:
        raise ConfigError(f"{label} must be a non-empty single-line string")
    path = Path(value)
    if "," in value or ":" in value:
        raise ConfigError(f"{label} contains a container-mount delimiter")
    if path.is_absolute() or any(part in ("", "..") for part in path.parts):
        raise ConfigError(f"{label} must stay beneath the repository root")
    normalized = path.as_posix()
    if normalized == "." and not allow_dot:
        raise ConfigError(f"{label} cannot name the repository root")
    return normalized


def container_repository(value: str) -> Path:
    if not value or any(character in value for character in (",", "\0", "\n", "\r")):
        raise ConfigError("container repository path contains a container-mount delimiter")
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise ConfigError("container repository path must be normalized and absolute")
    if path == Path("/src") or not path.is_relative_to("/src"):
        raise ConfigError("container repository path must stay beneath /src")
    return path


def _regular_unlinked(path: Path, label: str) -> None:
    try:
        stat = path.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"missing {label}: {path}") from error
    if path.is_symlink() or not path.is_file():
        raise ConfigError(f"{label} must be a regular file: {path}")
    if stat.st_nlink != 1:
        raise ConfigError(f"{label} must not be hard linked: {path}")


def validate_repository(repo: Path) -> Path:
    repo = repo.resolve(strict=True)
    if any(character in str(repo) for character in (",", "\n", "\r")):
        raise ConfigError("repository path contains a container-mount delimiter")
    sandbox = repo / ".agents" / "sandbox"
    current = repo
    for component in (".agents", "sandbox"):
        current /= component
        if current.is_symlink() or not current.is_dir():
            raise ConfigError(f"protected sandbox directory is missing or symlinked: {current}")
    manifest_path = sandbox / "proxy-commands.json"
    _regular_unlinked(manifest_path, "proxy manifest")
    validate_sandbox_tree(sandbox)
    repository_identity(repo)
    return repo


def validate_sandbox_tree(sandbox: Path) -> None:
    for root, directories, files in os.walk(sandbox, followlinks=False):
        for entry in [*directories, *files]:
            candidate = Path(root) / entry
            stat = candidate.lstat()
            if candidate.is_symlink():
                raise ConfigError(f"protected sandbox configuration contains a symlink: {candidate}")
            if candidate.is_file() and stat.st_nlink != 1:
                raise ConfigError(f"protected sandbox configuration contains a hard link: {candidate}")


def load_manifest(repo: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    sandbox = optional_sandbox_directory(repo)
    if sandbox is None:
        raise ConfigError("protected sandbox directory is missing")
    path = sandbox / "proxy-commands.json"
    _regular_unlinked(path, "proxy manifest")
    validate_sandbox_tree(sandbox)
    repository_identity(repo)
    bake = sandbox / "docker-bake.hcl"
    return load_manifest_file(path, default_bake=bake.is_file())


def optional_sandbox_directory(repo: Path) -> Path | None:
    current = repo
    for component in (".agents", "sandbox"):
        current /= component
        if not current.exists() and not current.is_symlink():
            return None
        if current.is_symlink() or not current.is_dir():
            raise ConfigError(f"protected sandbox directory is symlinked or invalid: {current}")
    return current


def load_optional_manifest(repo: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    repository_identity(repo)
    sandbox = optional_sandbox_directory(repo)
    if sandbox is None:
        return load_manifest_file(None)
    path = sandbox / "proxy-commands.json"
    if path.is_symlink():
        raise ConfigError(f"proxy manifest must not be symlinked: {path}")
    if not path.exists():
        bake = sandbox / "docker-bake.hcl"
        if not bake.exists():
            validate_sandbox_tree(sandbox)
            return load_manifest_file(None)
        _regular_unlinked(bake, "default Bake resolver")
        validate_sandbox_tree(sandbox)
        return load_manifest_file(None, default_bake=True)
    return load_manifest(repo)


def load_manifest_file(path: Path | None, *, default_bake: bool = False,
                       data: Any = None) -> dict[str, Any]:
    if data is not None:
        # In-memory accepted policy parsing must have no filesystem or resolver effects.
        try:
            data = json.loads(json.dumps(data), object_pairs_hook=_unique_object)
        except (TypeError, ValueError, ConfigError) as error:
            raise ConfigError(f"invalid accepted proxy manifest: {error}") from error
    elif path is None:
        data = {"version": 2, "commands": {}}
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ConfigError(f"invalid proxy manifest: {error}") from error
    if not isinstance(data, dict) or "version" not in data:
        raise ConfigError("proxy manifest must contain a version")
    version = data["version"]
    if version == 1:
        if not set(data) <= {"version", "commands", "capabilities", "images"} or "commands" not in data:
            raise ConfigError("version 1 proxy manifest has missing or unknown fields")
        capabilities = data.get("capabilities", {})
        images = data.get("images")
        if (not isinstance(capabilities, dict) or not set(capabilities) <= CAPABILITIES or
                not all(isinstance(value, bool) for value in capabilities.values())):
            raise ConfigError("proxy manifest has invalid capabilities")
    elif version == 2:
        if not set(data) <= {"version", "capabilities", "images", "commands"}:
            raise ConfigError("version 2 proxy manifest has unknown fields")
        capabilities = data.get("capabilities", {})
        if (not isinstance(capabilities, dict) or not set(capabilities) <= CAPABILITIES or
                not all(isinstance(value, bool) for value in capabilities.values())):
            raise ConfigError("proxy manifest has invalid capabilities")
        capabilities = {**CAPABILITY_DEFAULTS, **capabilities}
        images = data.get("images")
        if default_bake and images is None:
            images = {
                "resolver": {"kind": "bake", "file": ".agents/sandbox/docker-bake.hcl"},
                "base": "base",
            }
        if images is not None:
            if not isinstance(images, dict) or set(images) != {"resolver", "base"}:
                raise ConfigError("proxy manifest images must contain exactly resolver and base")
            resolver = images["resolver"]
            if not isinstance(resolver, dict) or resolver.get("kind") not in {"bake", "command"}:
                raise ConfigError("proxy manifest has an invalid image resolver")
            if resolver["kind"] == "bake":
                if not set(resolver) <= {"kind", "file"}:
                    raise ConfigError("Bake resolver may contain only kind and file")
                resolver = {
                    "kind": "bake",
                    "file": resolver.get("file", ".agents/sandbox/docker-bake.hcl"),
                }
                _plain_relative(resolver["file"], "Bake resolver file")
                images = {**images, "resolver": resolver}
            else:
                if set(resolver) != {"kind", "argv"}:
                    raise ConfigError("command resolver must contain exactly kind and argv")
                _string_array(resolver["argv"], "command resolver argv")
            if not isinstance(images["base"], str) or not NAME_RE.fullmatch(images["base"]):
                raise ConfigError("proxy manifest has an invalid base image name")
    else:
        raise ConfigError(f"unsupported proxy manifest version: {version!r}")
    raw_commands = data.get("commands", {})
    if not isinstance(raw_commands, dict):
        raise ConfigError("proxy manifest commands must be an object")
    commands: dict[str, Any] = {}
    targets: set[str] = set()
    for name, raw in raw_commands.items():
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ConfigError(f"invalid proxy command name: {name!r}")
        allowed = COMMAND_FIELDS | {'image-target'} if version == 1 else V2_COMMAND_FIELDS
        required = COMMAND_FIELDS - {'image-command'} if version == 1 else V2_COMMAND_FIELDS
        if (not isinstance(raw, dict) or not set(raw) <= allowed or not required <= set(raw) or
                (version == 1 and not {'image-command', 'image-target'} & set(raw))):
            raise ConfigError(f"command {name} has missing or unknown fields")
        image_command = _string_array(raw.get("image-command", []), f"command {name} image-command")
        if version == 2:
            if images is None:
                raise ConfigError(f"command {name} requires an explicit image resolver")
            if not isinstance(raw["image"], str) or not NAME_RE.fullmatch(raw["image"]):
                raise ConfigError(f"command {name} has an invalid image name")
        if 'image-target' in raw and (not isinstance(raw['image-target'], str) or
                                      not NAME_RE.fullmatch(raw['image-target'])):
            raise ConfigError(f"command {name} has invalid image-target")
        argv = _string_array(raw["argv"], f"command {name} argv")
        has_image = 'image-target' in raw if version == 1 else 'image' in raw
        if (not image_command and not has_image) or not argv or argv[0].startswith("/"):
            raise ConfigError(f"command {name} requires non-empty commands with a PATH-resolved argv")
        workdir = _plain_relative(raw["workdir"], f"command {name} workdir", allow_dot=True)
        if not isinstance(raw["network"], bool) or not isinstance(raw["mounts"], list):
            raise ConfigError(f"command {name} has invalid network or mounts")
        mounts = []
        local_targets: set[str] = set()
        local_builtins: set[str] = set()
        for index, mount in enumerate(raw["mounts"]):
            label = f"command {name} mount {index}"
            if isinstance(mount, dict) and "builtin" in mount:
                if set(mount) != BUILTIN_MOUNT_FIELDS or mount["builtin"] != "git":
                    raise ConfigError(f"{label} has missing or unknown built-in fields")
                if mount["proxy"] not in {"read-only", "read-write"} or mount["agent"] != "read-only":
                    raise ConfigError(f"{label} has an invalid built-in access mode")
                if mount["builtin"] in local_builtins:
                    raise ConfigError(f"duplicate proxy built-in mount: {mount['builtin']}")
                local_builtins.add(mount["builtin"])
                mounts.append(dict(mount))
                continue
            if not isinstance(mount, dict) or not set(mount) <= MOUNT_FIELDS or not {"source", "target"} <= set(mount):
                raise ConfigError(f"{label} has missing or unknown fields")
            source = _plain_relative(mount["source"], f"{label} source", allow_dot=True)
            target = _plain_relative(mount["target"], f"{label} target", allow_dot=True)
            proxy_mode = mount.get("proxy")
            agent_mode = mount.get("agent")
            if (proxy_mode is not None and proxy_mode not in MODES) or (agent_mode is not None and agent_mode not in MODES):
                raise ConfigError(f"{label} has an invalid access mode")
            if target in local_targets or target in targets:
                raise ConfigError(f"duplicate proxy mount target: {target}")
            if target == ".agents/sandbox" or target.startswith(".agents/sandbox/"):
                raise ConfigError(f"{label} may not hide protected sandbox configuration")
            if target == "." and (source != "." or proxy_mode != "read-write" or agent_mode is not None):
                raise ConfigError(f"{label} may grant only a proxy-only read-write repository view")
            protected_metadata = any(target == path or target.startswith(path + "/") for path in (".git", ".jj"))
            if protected_metadata and agent_mode not in {None, "read-only"}:
                raise ConfigError(f"{label} may not weaken protected repository metadata")
            local_targets.add(target)
            targets.add(target)
            mounts.append({"source": source, "target": target, "proxy": proxy_mode, "agent": agent_mode})
        normalized = {**raw, "image-command": image_command, "argv": argv, "workdir": workdir, "mounts": mounts}
        if version == 2:
            normalized["image-target"] = normalized.pop("image")
        commands[name] = normalized
    result = {"version": version, "commands": commands}
    if version == 2 or capabilities:
        result["capabilities"] = capabilities
    if images is not None:
        result["images"] = images
    return result


def write_atomic(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def serializable_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = {key: manifest[key] for key in ("version", "capabilities", "images") if key in manifest}
    result["commands"] = {}
    for name, command in manifest["commands"].items():
        mounts = []
        for mount in command["mounts"]:
            item = ({"builtin": mount["builtin"]} if "builtin" in mount else
                    {"source": mount["source"], "target": mount["target"]})
            for mode in ("proxy", "agent"):
                if mount[mode] is not None:
                    item[mode] = mount[mode]
            mounts.append(item)
        serialized = {**command, "mounts": mounts}
        if manifest.get("version") == 2 and "image-target" in serialized:
            serialized["image"] = serialized.pop("image-target")
            serialized.pop("image-command", None)
        result["commands"][name] = serialized
    return result


def checked_repository_path(repo: Path, relative: str, label: str) -> Path:
    current = repo
    for component in Path(relative).parts:
        current /= component
        try:
            current.lstat()
        except FileNotFoundError as error:
            raise ConfigError(f"missing {label}: {relative}") from error
        if current.is_symlink():
            raise ConfigError(f"{label} contains a symlinked component: {relative}")
    return current


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item or "\0" in item for item in value):
        raise ConfigError(f"{label} must be an array of non-empty strings")
    return value


def repository_identity(repo: Path) -> str:
    common = git_metadata_paths(repo)[1]
    identity = os.fsencode(repo.resolve(strict=True)) + b"\0" + os.fsencode(common)
    return hashlib.sha256(identity).hexdigest()


def use_repository_metadata(repo: Path, paths: tuple[Path, Path]) -> None:
    """Use the launcher's resolved metadata for this embedded helper's lifetime."""
    global REPOSITORY_METADATA
    validate_git_metadata(paths)
    REPOSITORY_METADATA = (repo.resolve(strict=True), paths)


def git_metadata_paths(repo: Path) -> tuple[Path, Path]:
    if REPOSITORY_METADATA is not None and repo.resolve(strict=True) == REPOSITORY_METADATA[0]:
        return REPOSITORY_METADATA[1]
    git_root = repo
    if not (repo / ".git").exists():
        try:
            backing = subprocess.run(
                ["jj", "--ignore-working-copy", "-R", str(repo), "git", "root"],
                check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            backing_path_text = backing.stdout.strip()
            backing_path = Path(backing_path_text)
            if not backing_path_text or not backing_path.is_absolute():
                raise ConfigError("Jujutsu returned an invalid Git metadata path")
            git_root = backing_path.resolve(strict=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise ConfigError(f"Git metadata cannot be resolved for repository: {repo}") from error
    try:
        result = subprocess.run(
            ["git", "-C", str(git_root), "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise ConfigError(f"Git metadata cannot be resolved for repository: {repo}") from error
    lines = result.stdout.splitlines()
    if len(lines) != 2:
        raise ConfigError("Git returned an invalid metadata layout")
    paths = tuple(Path(line).resolve(strict=True) for line in lines)
    validate_git_metadata(paths)
    return paths


def validate_git_metadata(paths: tuple[Path, Path]) -> None:
    if len(paths) != 2:
        raise ConfigError("Git returned an invalid metadata layout")
    for path in paths:
        if any(character in str(path) for character in (",", "\n", "\r")):
            raise ConfigError("Git metadata path contains a container-mount delimiter")
        if not path.is_dir() or path.is_symlink():
            raise ConfigError(f"Git metadata directory is invalid: {path}")


def metadata_container_path(repo: Path, host_path: Path, container_repo: Path) -> Path:
    repo = repo.resolve(strict=True)
    host_path = host_path.resolve(strict=True)
    relative = Path(os.path.relpath(host_path, repo))
    target = Path(os.path.normpath(container_repo / relative))
    try:
        target.relative_to("/src")
    except ValueError as error:
        raise ConfigError(f"repository metadata path escapes the container workspace: {host_path}") from error
    return target


def metadata_mounts(repo: Path, container_repo: Path, paths: set[Path]) -> list[tuple[Path, Path]]:
    repo = repo.resolve(strict=True)
    candidates = sorted(paths, key=lambda path: (len(path.parts), str(path)))
    mounts: list[tuple[Path, Path]] = []
    for source in candidates:
        if any(source.is_relative_to(parent) for parent, _ in mounts):
            continue
        mounts.append((source, metadata_container_path(repo, source, container_repo)))
    return mounts


def git_proxy_metadata_mounts(repo: Path, container_repo: Path) -> list[tuple[Path, Path]]:
    return metadata_mounts(repo, container_repo, set(git_metadata_paths(repo)))


def jj_proxy_metadata_mounts(repo: Path, container_repo: Path) -> list[tuple[Path, Path]]:
    git_dir, common_dir = git_metadata_paths(repo)
    return metadata_mounts(repo, container_repo, {git_dir, common_dir, jj_repository_path(repo)})


def jj_repository_path(repo: Path) -> Path:
    entry = repo / ".jj" / "repo"
    if entry.is_file() and not entry.is_symlink():
        if entry.lstat().st_nlink != 1:
            raise ConfigError("Jujutsu repository pointer must not be hard linked")
        try:
            value = entry.read_text(encoding="utf-8").strip()
        except UnicodeError as error:
            raise ConfigError("Jujutsu repository pointer is not UTF-8") from error
        if not value or "\0" in value or "\n" in value or "\r" in value:
            raise ConfigError("Jujutsu repository pointer is invalid")
        target = Path(value)
        if not target.is_absolute():
            target = entry.parent / target
        jj_repo = target.resolve(strict=True)
    else:
        jj_repo = entry.resolve(strict=True)
    if not jj_repo.is_dir() or jj_repo.is_symlink():
        raise ConfigError(f"Jujutsu repository metadata is invalid: {jj_repo}")
    return jj_repo


def runtime_directory(repo: Path) -> Path:
    base = Path.home() / ".cache" / "codex-sandbox-proxies"
    path = base / repository_identity(repo)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def recoverable_session_state(metadata: object) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    if not isinstance(metadata.get("state"), dict) and metadata.get("version") != 4:
        return None
    return session_state(metadata)


def recorded_proxy_volumes(state: dict[str, Any]) -> set[str]:
    volumes = {
        proxy["volume"] for proxy in [*state.get("proxies", []), *state.get("retired-proxies", [])]
        if isinstance(proxy, dict) and isinstance(proxy.get("volume"), str)
    }
    auth = state.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("socket-volume"), str):
        volumes.add(auth["socket-volume"])
    return volumes


def reset_main(args: argparse.Namespace) -> int:
    runtime = runtime_directory(Path(args.repo))
    coordination_path = runtime / "coordination.lock"
    session_path = runtime / "session.lock"
    with coordination_path.open("a+b") as coordination, session_path.open("a+b") as session:
        fcntl.flock(coordination, fcntl.LOCK_EX)
        try:
            fcntl.flock(session, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ConfigError("sandbox sessions are still active") from error
        metadata_path = runtime / "session.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            metadata = None
        state = recoverable_session_state(metadata)
        if state is not None:
            try:
                stop_state(state)
            except BaseException:
                if metadata.get("version") == 4:
                    for role, service in metadata["services"].items():
                        recovery = next((p for p in state.get("proxies", []) if p.get("name") == role), None)
                        if role == "codex-broker":
                            recovery = state.get("auth")
                        if recovery is not None:
                            service["recovery"] = recovery
                    write_atomic(metadata_path, json.dumps(metadata, sort_keys=True))
                    os.chmod(metadata_path, 0o600)
                elif state.get("trusted-services") == SESSION_LIFECYCLE_SCHEMA:
                    metadata["state"] = state
                    write_atomic(metadata_path, json.dumps(metadata, sort_keys=True))
                raise
        metadata_path.unlink(missing_ok=True)
    return 0


def publish_main(args: argparse.Namespace) -> int:
    """Publish one complete, strictly parsed schema-4 authority."""
    runtime = runtime_directory(Path(args.repo))
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    owner = runtime_identity(OUTER_RUNTIME)
    if state.get("runtime") != owner:
        raise ConfigError("cannot publish shared state owned by another runtime")
    state["runtime"] = owner
    manifest = load_manifest_file(Path(args.manifest))
    launch = state.get("accepted")
    if not isinstance(launch, dict) or set(launch) != {
            "source-present", "agent-image", "helper-image", "parameters", "proxy-images"}:
        raise ConfigError("shared state is missing accepted launch authority")
    parameters = launch["parameters"]
    proxies = state.get("proxies")
    proxy_roles = [p.get("name") for p in proxies if isinstance(p, dict)] if isinstance(proxies, list) else []
    if len(proxy_roles) != len(set(proxy_roles)):
        raise ConfigError("shared state contains duplicate service roles")
    if not isinstance(proxies, list) or len(proxy_roles) != len(proxies) or set(proxy_roles) != set(manifest["commands"]):
        raise ConfigError("shared state is missing required services")
    if launch["proxy-images"] != {p["name"]: p.get("image") for p in proxies}:
        raise ConfigError("published proxy images differ from accepted launch images")
    zulip = next((proxy for proxy in proxies if proxy.get("name") == "zulip"), None)
    if zulip is not None and zulip.get("helper-image") != launch["helper-image"]:
        raise ConfigError("published Zulip helper differs from accepted owned image")
    validate_live_proxies(OUTER_RUNTIME, proxies, repository_identity(Path(args.repo)),
                          commands=manifest["commands"], uid=parameters.get("uid"), gid=parameters.get("gid"))
    services = {p["name"]: _service_record(p["name"], p, owner) for p in proxies}
    auth = state.get("auth")
    if auth is not None:
        try:
            kind, auth = parse_auth_record(auth, managed_required=True)
        except ValueError as error:
            raise ConfigError("shared state has invalid authentication recovery authority") from error
        if (kind != "managed" or auth["lifecycle-state"] != "ready" or
                auth["resource-status"] != {field: "created" for field in PAIR_STATUS_FIELDS}):
            raise ConfigError("authentication service is not ready for publication")
        snapshot = OUTER_RUNTIME.inspect_container(auth["container"])
        if snapshot.get("State", {}).get("Running") is not True:
            raise ConfigError("authentication service stopped before publication")
        _validate_codex_broker(OUTER_RUNTIME, auth, launch["helper-image"], parameters["uid"], parameters["gid"], snapshot=snapshot)
        published_auth = dict(auth)
        published_auth["lifecycle-state"] = "published"
        services["codex-broker"] = _service_record("codex-broker", published_auth, owner)
    payload = {
        "version": 4, "repository": repository_identity(Path(args.repo)),
        "container_repository": str(container_repository(args.container_repo)),
        "runtime-owner": owner,
        "accepted": {"policy": serializable_manifest(manifest),
                     "source-present": launch["source-present"],
                     "broker-roles": sorted(set(services) - set(manifest["commands"])),
                     "images": {"agent": launch["agent-image"], "helper": launch["helper-image"],
                                "services": {role: service["container"]["image"] for role, service in services.items()}},
                     "image-bound-parameters": parameters},
        "services": services,
    }
    # Parse the complete in-memory payload before the sole atomic replacement.
    _accepted_schema4(payload, expected_parameters=parameters)
    write_atomic(runtime / "session.json", json.dumps(payload, sort_keys=True))
    os.chmod(runtime / "session.json", 0o600)
    return 0

def session_state(metadata):
    """Return recovery state for all historical schemas and the schema-4 service set."""
    version = metadata.get("version")
    if version == 4:
        services = metadata.get("services")
        envelope_runtime = metadata.get("runtime-owner")
        if not isinstance(services, dict) or not _valid_runtime_owner(envelope_runtime):
            raise ConfigError("schema-4 session has invalid recovery authority")
        runtimes = []
        proxies, auth = [], None
        for role, service in services.items():
            parsed = _parse_service_record(role, service)
            runtimes.append(parsed["runtime-owner"])
            recovery = parsed["recovery"]
            if parsed["family"] == "command-proxy" or role == "zulip":
                proxies.append(recovery)
            elif role == "codex-broker":
                auth = recovery
            else:
                raise ConfigError("schema-4 session contains an unknown service role")
        if any(owner != envelope_runtime for owner in runtimes):
            raise ConfigError("schema-4 services disagree with envelope runtime owner")
        state = {"runtime": envelope_runtime, "proxies": proxies,
                 "trusted-services": SESSION_LIFECYCLE_SCHEMA}
        if auth is not None:
            state["auth"] = auth
        return state
    if version not in (1, 2, 3) or not isinstance(metadata.get("state"), dict):
        raise ConfigError("unsupported shared-session schema; retain metadata for explicit recovery")
    state = metadata["state"]
    if version == 1:
        if state.get("runtime") == {"provider": "podman"}:
            raise ConfigError("legacy session state uses the removed Podman backend")
        if "runtime" in state:
            raise ConfigError("legacy session state has an unsupported runtime owner")
    elif "runtime" not in state:
        raise ConfigError("shared-session metadata is missing its runtime owner")
    return state


_SERVICE_FIELDS = {"family", "implementation-identity", "state-schema", "container",
                   "endpoints", "runtime-owner", "recovery-identity", "recovery"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")


def _valid_runtime_owner(value: Any) -> bool:
    if value == {"provider": "container"}:
        return True
    if not isinstance(value, dict) or value.get("provider") not in {"lima", "lima-docker"}:
        return False
    fields = {"provider", "state", "instance", "generation", "namespace", "vm_identity", "network_digest"}
    if value.get("provider") == "lima-docker":
        fields |= {"engine_id", "network_id"}
    return (set(value) == fields and all(isinstance(item, str) and item for item in value.values())
            and Path(value["state"]).is_absolute())


def _parse_service_record(role: str, value: Any) -> dict[str, Any]:
    if not isinstance(role, str) or not NAME_RE.fullmatch(role) or not isinstance(value, dict):
        raise ConfigError("invalid schema-4 service record")
    fields = set(value)
    if fields not in (_SERVICE_FIELDS, _SERVICE_FIELDS | {"broker-session-token"}):
        raise ConfigError("schema-4 service has missing or unknown fields")
    container = value.get("container")
    endpoints = value.get("endpoints")
    runtime = value.get("runtime-owner")
    recovery = value.get("recovery")
    family = value.get("family")
    if (family not in {"command-proxy", "authenticated-egress"} or
            not isinstance(value.get("implementation-identity"), str) or
            not IMAGE_RE.fullmatch(value["implementation-identity"]) or
            value.get("state-schema") != 1 or
            not isinstance(container, dict) or set(container) != {"name", "image", "owner"} or
            not all(isinstance(container.get(k), str) and container[k] for k in container) or
            not isinstance(endpoints, list) or len(endpoints) != 1 or
            not isinstance(endpoints[0], dict) or
            not _valid_runtime_owner(runtime) or
            not isinstance(value.get("recovery-identity"), str) or
            value["recovery-identity"] != container["owner"] or
            not isinstance(recovery, dict) or recovery.get("container") != container["name"] or
            recovery.get("image") != container["image"] or
            recovery.get("service-owner") != container["owner"] or
            recovery.get("implementation-identity") != value["implementation-identity"] or
            recovery.get("state-schema") != value["state-schema"]):
        raise ConfigError("schema-4 service identity is invalid")
    try:
        if family == "command-proxy":
            parsed_recovery = _managed_proxy_record(recovery)
            if parsed_recovery is None or role == "zulip":
                raise ConfigError("schema-4 command recovery has the wrong family")
            endpoint_fields = {"container", "socket"} | ({"forward"} if "forwarding" in recovery else set())
            if set(endpoints[0]) != endpoint_fields or endpoints[0].get("socket") != "/run/sandbox-proxy/socket":
                raise ConfigError("schema-4 command endpoint is invalid")
        elif role == "zulip":
            parsed_recovery = _managed_proxy_record(recovery)
            endpoint_fields = {"container", "socket"} | ({"forward"} if "forwarding" in recovery else set())
            if parsed_recovery is None or set(endpoints[0]) != endpoint_fields or endpoints[0].get("socket") != "/run/sandbox-proxy/socket":
                raise ConfigError("schema-4 Zulip endpoint is invalid")
        elif role == "codex-broker":
            kind, _ = parse_auth_record(recovery, managed_required=True)
            if kind != "managed" or set(endpoints[0]) != {"container", "port"} or endpoints[0].get("port") != 8787:
                raise ConfigError("schema-4 Codex endpoint is invalid")
        else:
            raise ConfigError("schema-4 authenticated service has an unknown role")
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigError("schema-4 service recovery authority is invalid") from error
    endpoint = endpoints[0]
    if endpoint.get("container") != container["name"]:
        raise ConfigError("schema-4 endpoint names another container")
    endpoint_forward = endpoint.get("forward")
    recovery_forward = recovery.get("forwarding")
    if ((endpoint_forward is None) != (recovery_forward is None) or
            endpoint_forward is not None and (
                not isinstance(endpoint_forward, dict) or endpoint_forward != recovery_forward or
                endpoint_forward.get("owner") != container["owner"])):
        raise ConfigError("schema-4 endpoint forwarding owner is invalid")
    token = value.get("broker-session-token")
    if token is not None and (not isinstance(token, str) or not _TOKEN_RE.fullmatch(token)):
        raise ConfigError("schema-4 broker token is invalid")
    if (value["family"] == "authenticated-egress") != (token is not None):
        raise ConfigError("schema-4 broker token authority is invalid")
    expected_token = recovery.get("key") if role == "codex-broker" else recovery.get("session-token")
    if token is not None and token != expected_token:
        raise ConfigError("schema-4 broker token differs from recovery authority")
    if role == "codex-broker" and recovery.get("runtime-owner") != runtime:
        raise ConfigError("schema-4 broker runtime owner is invalid")
    return value


def _service_record(role: str, recovery: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    family = recovery.get("family", "command-proxy")
    endpoint = dict(recovery.get("endpoint", {"container": recovery["container"],
                                              "socket": "/run/sandbox-proxy/socket"}))
    if "forwarding" in recovery:
        endpoint["forward"] = recovery["forwarding"]
    result = {
        "family": family, "implementation-identity": recovery["implementation-identity"],
        "state-schema": recovery["state-schema"],
        "container": {"name": recovery["container"], "image": recovery["image"],
                      "owner": recovery["service-owner"]},
        "endpoints": [endpoint], "runtime-owner": runtime,
        "recovery-identity": recovery["service-owner"], "recovery": recovery,
    }
    token = recovery.get("session-token", recovery.get("key"))
    if family == "authenticated-egress" or role == "codex-broker":
        result["family"] = "authenticated-egress"
        result["broker-session-token"] = token
    return result


def containers_running(containers: list[str]) -> bool:
    if not containers:
        return True
    inspection = subprocess.run(
        OUTER_RUNTIME.argv(["inspect", "--format", "{{.State.Running}}", *containers]),
        check=False, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return inspection.returncode == 0 and inspection.stdout.splitlines() == ["true"] * len(containers)


def cached_session_state(
    args: argparse.Namespace, repo: Path, metadata: Any, manifest: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(metadata, dict) or metadata.get("version") not in (1, 2):
        return None
    if metadata.get("repository") != repository_identity(repo):
        return None
    if metadata.get("container_repository") != str(container_repository(args.container_repo)):
        return None
    state = session_state(metadata)
    if state.get("runtime") != runtime_identity(OUTER_RUNTIME):
        return None
    cached_manifest = metadata.get("manifest")
    if not isinstance(state, dict) or not isinstance(state.get("proxies"), list):
        return None
    auth = state.get("auth")
    if bool(auth) != getattr(args, "auth_enabled", False):
        return None
    if auth and (not isinstance(auth, dict) or auth.get("image") != args.helper_image):
        return None
    if cached_manifest != serializable_manifest(manifest):
        return None
    proxies = state["proxies"]
    if {
        proxy.get("name") for proxy in proxies if isinstance(proxy, dict)
    } != set(manifest["commands"]):
        return None
    containers = [proxy.get("container") for proxy in proxies]
    if any(not isinstance(container, str) or not container for container in containers):
        return None
    try:
        snapshots = None
        if OUTER_RUNTIME.provider == 'lima-docker':
            with ThreadPoolExecutor(max_workers=2) as executor:
                snapshots = dict(zip(containers, executor.map(OUTER_RUNTIME.inspect_container, containers)))
            if not all(raw.get('State', {}).get('Running') is True for raw in snapshots.values()):
                return None
        elif not containers_running(containers):
            return None
        validate_live_proxies(OUTER_RUNTIME, proxies, repository_identity(repo),
                              snapshots=snapshots, commands=manifest["commands"])
        if OUTER_RUNTIME.provider == 'lima-docker':
            from lima.proxy_forward import check
            for proxy in proxies:
                if not proxy.get('volume-owner'):
                    return None
                if proxy.get('forwarding') != OUTER_RUNTIME.proxy_forward_record(
                        proxy['container'], proxy.get('volume-owner'), snapshot=snapshots[proxy['container']]):
                    return None
                check(proxy['forwarding']['owner'])
    except (ValueError, OSError, ConfigError, subprocess.SubprocessError):
        return None
    return state


def _accepted_schema4(metadata: Any, *, expected_parameters: dict[str, int]):
    if not isinstance(metadata, dict) or set(metadata) != {
            "version", "repository", "container_repository", "runtime-owner", "accepted", "services"} or metadata.get("version") != 4:
        raise ConfigError("invalid schema-4 shared-session envelope")
    if not _valid_runtime_owner(metadata.get("runtime-owner")):
        raise ConfigError("active session has invalid runtime owner")
    accepted = metadata.get("accepted")
    if not isinstance(accepted, dict) or set(accepted) != {
            "policy", "source-present", "broker-roles", "images", "image-bound-parameters"}:
        raise ConfigError("active session has invalid accepted authority")
    images = accepted.get("images")
    services = metadata.get("services")
    if (not isinstance(accepted["policy"], dict) or not isinstance(accepted["source-present"], bool) or
            not isinstance(images, dict) or set(images) != {"agent", "helper", "services"} or
            not isinstance(images["agent"], str) or not images["agent"] or
            images["helper"] is not None and not isinstance(images["helper"], str) or
            not isinstance(images["services"], dict) or not isinstance(services, dict)):
        raise ConfigError("active session has invalid accepted images")
    try:
        policy = load_manifest_file(None, data=accepted["policy"])
    except ConfigError as error:
        raise ConfigError("active session has invalid accepted policy") from error
    service_roles = list(services)
    if len(service_roles) != len(set(service_roles)):
        raise ConfigError("active session contains duplicate service roles")
    parsed = {role: _parse_service_record(role, service) for role, service in services.items()}
    if any(service["runtime-owner"] != metadata["runtime-owner"] for service in parsed.values()):
        raise ConfigError("active session services disagree with envelope runtime owner")
    commands = policy["commands"]
    broker_roles = accepted["broker-roles"]
    if (not isinstance(broker_roles, list) or len(broker_roles) != len(set(broker_roles)) or
            any(role != "codex-broker" for role in broker_roles)):
        raise ConfigError("active session has invalid accepted broker selection")
    expected_roles = set(commands) | set(broker_roles)
    if set(parsed) != expected_roles or images["services"] != {
            role: service["container"]["image"] for role, service in parsed.items()}:
        raise ConfigError("active session service set does not match accepted policy and images")
    if accepted["image-bound-parameters"] != expected_parameters:
        raise ConfigError("active session image-bound parameters changed")
    accepted = {**accepted, "policy": policy}
    return parsed, accepted


def accepted_session(args: argparse.Namespace, repo: Path, metadata: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    # Active schema 1-3 is recovery-only. In particular, never consult current
    # repository policy or resolvers while deciding whether it may be joined.
    if not isinstance(metadata, dict) or metadata.get("version") != 4:
        raise ConfigError("active session is not schema 4; restart after active sandboxes exit")
    parsed4, accepted4 = _accepted_schema4(metadata, expected_parameters={"uid": args.uid, "gid": args.gid})
    state = session_state(metadata)
    accepted = {"manifest": accepted4["policy"], "source-present": accepted4["source-present"],
                "images": {"agent": accepted4["images"]["agent"],
                           "helper": accepted4["images"]["helper"],
                           "caddy": (parsed4["codex-broker"]["container"]["image"]
                                     if "codex-broker" in parsed4 else None),
                           "proxies": {name: image for name, image in accepted4["images"]["services"].items()
                                       if name != "codex-broker"}},
                "parameters": accepted4["image-bound-parameters"]}
    metadata = {**metadata, "version": 3, "state": state, "accepted": accepted}
    if metadata.get("repository") != repository_identity(repo):
        raise ConfigError("active session belongs to another repository")
    if metadata.get("container_repository") != str(container_repository(args.container_repo)):
        raise ConfigError("active session uses another container repository")
    state = session_state(metadata)
    if state.get("runtime") != runtime_identity(OUTER_RUNTIME):
        raise ConfigError("active session uses another runtime provider")
    accepted = metadata.get("accepted")
    if not isinstance(accepted, dict) or set(accepted) != {
        "manifest", "source-present", "images", "parameters",
    }:
        raise ConfigError("active session has invalid accepted authority")
    manifest = accepted["manifest"]
    images = accepted["images"]
    parameters = accepted["parameters"]
    if (not isinstance(accepted["source-present"], bool) or
            not isinstance(manifest, dict) or not isinstance(images, dict) or
            set(images) != {"agent", "helper", "caddy", "proxies"} or
            not isinstance(images["proxies"], dict) or
            set(images["proxies"]) != set(manifest.get("commands", {})) or
            not isinstance(images["agent"], str) or not images["agent"] or
            images["helper"] is not None and (
                not isinstance(images["helper"], str) or not images["helper"]
            ) or not all(isinstance(value, str) and value for value in images["proxies"].values()) or
            parameters != {"uid": args.uid, "gid": args.gid}):
        raise ConfigError("active session has invalid accepted images or image-bound parameters")
    if (getattr(args, "agent_image", images["agent"]) != images["agent"] or
            getattr(args, "helper_image", images["helper"]) != images["helper"]):
        raise ConfigError("active session image selection changed before attachment")
    proxies = state.get("proxies")
    if not isinstance(proxies, list) or {
        proxy.get("name") for proxy in proxies if isinstance(proxy, dict)
    } != set(manifest["commands"]):
        raise ConfigError("active session proxy state does not match accepted policy")
    if {proxy["name"]: proxy.get("image") for proxy in proxies} != images["proxies"]:
        raise ConfigError("active session proxy images do not match accepted images")
    zulip = next((proxy for proxy in proxies if proxy.get("name") == "zulip"), None)
    if zulip is not None and (images["helper"] is None or zulip.get("helper-image") != images["helper"]):
        raise ConfigError("active session Zulip helper image differs from accepted owned identity")
    lifecycle_schema = state.get("trusted-services")
    if lifecycle_schema not in (None, SESSION_LIFECYCLE_SCHEMA):
        raise ConfigError("active session has an unsupported trusted-service schema")
    auth = state.get("auth")
    auth_kind = None
    if auth is not None:
        try:
            auth_kind, auth = parse_auth_record(
                auth, managed_required=lifecycle_schema == SESSION_LIFECYCLE_SCHEMA)
        except ValueError as error:
            raise ConfigError("active session has invalid authentication state") from error
        if (images["helper"] is None or auth_kind != "managed" or
                auth["image"] != images["caddy"]):
            raise ConfigError("active session authentication images do not match accepted images")
        if (auth["lifecycle-state"] != "published" or
                auth["resource-status"] != {field: "created" for field in PAIR_STATUS_FIELDS}):
            raise ConfigError("active session authentication service was not published")
    try:
        OUTER_RUNTIME.verify_builder_image(images["agent"])
        helper_image = None
        if images["helper"] is not None:
            helper_image = OUTER_RUNTIME.verify_builder_image(images["helper"])
        for image in images["proxies"].values():
            OUTER_RUNTIME.verify_builder_image(image)
        if auth is not None:
            if not isinstance(auth.get("container"), str) or helper_image is None:
                raise ConfigError("active session has invalid authentication state")
            if auth_kind == "managed":
                auth_snapshot = OUTER_RUNTIME.inspect_container(auth["container"])
                if auth_snapshot.get("State", {}).get("Running") is not True:
                    raise ConfigError("active session has an unhealthy authentication service")
                _validate_codex_broker(OUTER_RUNTIME, auth, images["helper"], args.uid, args.gid,
                                       snapshot=auth_snapshot)
            elif (not containers_running([auth["container"]]) or
                  not OUTER_RUNTIME.container_matches_image(auth["container"], helper_image)):
                raise ConfigError("active session has an unhealthy authentication service")
        containers = [proxy["container"] for proxy in proxies]
        snapshots = None
        if OUTER_RUNTIME.provider == "lima-docker":
            with ThreadPoolExecutor(max_workers=2) as executor:
                snapshots = dict(zip(containers, executor.map(OUTER_RUNTIME.inspect_container, containers)))
            if not all(snapshot.get("State", {}).get("Running") is True for snapshot in snapshots.values()):
                raise ConfigError("active session has a stopped proxy")
        elif not containers_running(containers):
            raise ConfigError("active session has a stopped proxy")
        validate_live_proxies(
            OUTER_RUNTIME, proxies, repository_identity(repo), snapshots=snapshots,
            commands=manifest["commands"], uid=args.uid, gid=args.gid,
        )
        if OUTER_RUNTIME.provider == "lima-docker":
            from lima.proxy_forward import check
            for proxy in proxies:
                forwarding = proxy.get("forwarding")
                if not proxy.get("volume-owner") or forwarding != OUTER_RUNTIME.proxy_forward_record(
                    proxy["container"], proxy["volume-owner"], snapshot=snapshots[proxy["container"]],
                ):
                    raise ConfigError("active session proxy forwarding changed")
                check(forwarding["owner"])
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise ConfigError(f"active session image or service validation failed: {error}") from error
    return state, accepted


def _read_session(path: Path) -> Any:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                stat.S_IMODE(info.st_mode) != 0o600):
            raise ConfigError(
                "active session metadata must be a regular file owned by the current uid with mode 0600"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            return json.load(stream, object_pairs_hook=_unique_object)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError, OSError) as error:
        raise ConfigError("active session metadata is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def join_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    path = runtime_directory(repo) / "session.json"
    metadata = _read_session(path)
    state, accepted = accepted_session(args, repo, metadata)
    write_atomic(Path(args.state), json.dumps(state, sort_keys=True))
    write_atomic(Path(args.manifest), json.dumps(accepted["manifest"], sort_keys=True))
    write_atomic(Path(args.images), json.dumps(accepted["images"]["proxies"], sort_keys=True))
    write_atomic(Path(args.accepted), json.dumps({
        "source-present": accepted["source-present"],
        "agent-image": accepted["images"]["agent"],
        "helper-image": accepted["images"]["helper"],
    }, sort_keys=True))
    return 0


def attach_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    runtime = runtime_directory(repo)
    shared = args.shared
    metadata_path = runtime / "session.json"
    try:
        metadata = _read_session(metadata_path)
    except ConfigError:
        if shared:
            raise
        # An unparseable local cache cannot authorize recovery. Do not let it
        # block a fresh exclusive session.
        metadata_path.unlink(missing_ok=True)
        metadata = None
    if shared:
        state, accepted = accepted_session(args, repo, metadata)
        write_atomic(Path(args.state), json.dumps(state, sort_keys=True))
        write_atomic(Path(args.manifest), json.dumps(accepted["manifest"], sort_keys=True))
        return 0
    current_manifest = load_manifest_file(Path(args.manifest))
    state = cached_session_state(args, repo, metadata, current_manifest)
    if state is not None:
        write_atomic(Path(args.state), json.dumps(state, sort_keys=True))
        return 0
    previous = recoverable_session_state(metadata)
    if previous is not None:
        old_owner = previous.get("runtime")
        current_owner = runtime_identity(OUTER_RUNTIME)
        replaced_vm = (isinstance(old_owner, dict) and
                       old_owner.get("provider") == current_owner.get("provider") == "lima-docker" and
                       all(old_owner.get(key) == current_owner.get(key)
                           for key in ("state", "instance", "namespace")) and
                       all(old_owner.get(key) != current_owner.get(key)
                           for key in ("generation", "vm_identity", "engine_id", "network_id")))
        if replaced_vm:
            # The old resources cannot exist in this new VM. Retain their
            # recovery authority without applying it to the replacement.
            archived = runtime / f"session.replaced-{uuid.uuid4().hex}.json"
            metadata_path.rename(archived)
            print(f"Sandbox proxies: preserved replaced VM session at {archived}", file=sys.stderr)
        else:
            stop_state(previous)
    metadata_path.unlink(missing_ok=True)
    start_main(args)
    return 0


def resolve_images(repo: Path, manifest: dict[str, Any], prepared=None) -> dict[str, str]:
    if prepared is not None:
        images = json.loads(Path(prepared).read_text())
        if (not isinstance(images, dict) or set(images) != set(manifest['commands']) or
                not all(isinstance(image, str) for image in images.values())):
            raise ConfigError('prepared images do not match the proxy manifest')
        return {
            name: OUTER_RUNTIME.verify_builder_image(image).reference
            for name, image in images.items()
        }
    if OUTER_RUNTIME.provider == 'lima-docker':
        from image_resolver import prepare_launch_images
        options = ({"image_policy": manifest["images"]} if "images" in manifest else {})
        return prepare_launch_images(OUTER_RUNTIME, repo, manifest['commands'], **options).proxies
    policy = manifest.get("images")
    if policy is not None:
        resolver = policy["resolver"]
        if resolver["kind"] != "command":
            raise ConfigError(
                f"bundled Bake resolver is unavailable for {OUTER_RUNTIME.provider}"
            )
        from image_resolver import ResolverError, resolve_command
        bindings = {name: command["image-target"] for name, command in manifest["commands"].items()}
        try:
            resolved = resolve_command(OUTER_RUNTIME, repo, resolver["argv"], set(bindings.values()))
        except ResolverError as error:
            raise ConfigError(str(error)) from error
        return {name: resolved[target].reference for name, target in bindings.items()}
    def resolve(name: str, command: dict[str, Any]) -> tuple[str, str]:
        if not command.get('image-command'):
            raise ConfigError(f"proxy {name} uses Bake targets; select CODEX_SANDBOX_RUNTIME=lima-docker")
        result = subprocess.run(command["image-command"], cwd=repo, text=True, stdout=subprocess.PIPE)
        output = result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout
        if BARE_IMAGE_RE.fullmatch(output):
            output = "sha256:" + output
        if result.returncode or result.stdout.count("\n") > 1:
            raise ConfigError(f"image-command for {name} did not print exactly one immutable image hash")
        try:
            return name, OUTER_RUNTIME.builder_image(output)
        except ValueError as error:
            raise ConfigError(f"image-command for {name}: {error}") from error

    commands = manifest["commands"]
    with ThreadPoolExecutor(max_workers=max(1, len(commands))) as executor:
        return dict(executor.map(lambda item: resolve(*item), commands.items()))


def _docker(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return OUTER_RUNTIME.run(
        list(arguments), check=True, text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def proxy_logs(container: str) -> str:
    result = subprocess.run(
        OUTER_RUNTIME.argv(["logs", "--tail", "200", container]), check=False, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def proxy_repository_mount_args(
    repo: Path, container_repo: Path, name: str, command: dict[str, Any],
) -> list[str]:
    repo = repo.resolve(strict=True)
    repository_mode = ",readonly"
    if any(mount.get("target") == "." and mount["proxy"] == "read-write" for mount in command["mounts"]):
        repository_mode = ""
    arguments = [
        "--mount", f"type=bind,src={repo},dst={container_repo}{repository_mode},{OUTER_RUNTIME.nonrecursive_bind}",
    ]
    if name == "jj":
        metadata_mounts = jj_proxy_metadata_mounts(repo, container_repo)
        host_src = Path.home() / "src"
        if host_src.is_dir() and not any(target == Path("/src") for _, target in metadata_mounts):
            host_src = host_src.resolve(strict=True)
            arguments += ["--mount", f"type=bind,src={host_src},dst=/src,readonly,{OUTER_RUNTIME.nonrecursive_bind}"]
        for source, target in metadata_mounts:
            arguments += [
                "--mount", f"type=bind,src={source},dst={target}{repository_mode}",
            ]
    sandbox = optional_sandbox_directory(repo)
    if sandbox is not None:
        arguments += [
            "--mount", f"type=bind,src={sandbox},dst={container_repo / '.agents/sandbox'},readonly",
        ]
    for mount in command["mounts"]:
        if mount.get("builtin") == "git":
            suffix = ",readonly" if mount["proxy"] == "read-only" else ""
            for source, target in git_proxy_metadata_mounts(repo, container_repo):
                arguments += ["--mount", f"type=bind,src={source},dst={target}{suffix}"]
            continue
        source = checked_repository_path(repo, mount["source"], f"command {name} mount source")
        checked_repository_path(repo, mount["target"], f"command {name} mount target")
        target = container_repo / mount["target"]
        mode = mount["proxy"]
        if mount["target"] == "." or mode is None:
            continue
        if mode == "hidden":
            arguments += ["--tmpfs", f"{target}:ro,noexec,nosuid,nodev,size=4k"]
        else:
            suffix = ",readonly" if mode == "read-only" else ""
            arguments += ["--mount", f"type=bind,src={source},dst={target}{suffix}"]
    try:
        check_mount_destinations(arguments)
    except ValueError as error:
        raise ConfigError(str(error)) from error
    return arguments


def proxy_git_environment_args(repo: Path, container_repo: Path, command: dict[str, Any]) -> list[str]:
    if not any(mount.get("builtin") == "git" for mount in command["mounts"]):
        return []
    common_dir = git_metadata_paths(repo)[1]
    return ["--env", f"SANDBOX_GIT_DIR={metadata_container_path(repo, common_dir, container_repo)}"]


def zulip_credential_identity(path: Path) -> str:
    metadata = path.stat()
    material = [metadata.st_dev, metadata.st_ino, metadata.st_uid, metadata.st_mode & 0o777]
    return "sha256:" + hashlib.sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()


def zulip_site(path: Path) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as stream:
            parser.read_file(stream)
        site = parser.get("api", "site").rstrip("/")
    except (OSError, configparser.Error) as error:
        raise ConfigError("Zulip credentials do not contain a readable site") from error
    from urllib.parse import urlsplit
    parsed = urlsplit(site)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ConfigError("Zulip site must be a plain HTTPS server origin")
    return parsed.hostname


def _zulip_mounts_exact(caddy: dict[str, Any], helper: dict[str, Any], *, socket_name: str,
                        socket_source: str, config_source: str, credential_source: str) -> bool:
    def projection(item):
        return {(mount.get("Destination"), mount.get("Source"), mount.get("RW"),
                 mount.get("Type"), mount.get("Name")) for mount in item.get("Mounts", [])}
    return projection(caddy) == {
        ("/run/profile-helper", socket_source, False, "volume", socket_name),
        ("/etc/caddy/caddy.json", config_source, False, "bind", None),
    } and projection(helper) == {
        ("/run/profile-helper", socket_source, True, "volume", socket_name),
        ("/run/secrets/zuliprc", credential_source, False, "bind", None),
    }


def _zulip_container_hardened(item: dict[str, Any], *, role: str, uid: int, gid: int,
                              network: str, entrypoint: Any, command: list[str]) -> bool:
    config, host = item.get("Config", {}), item.get("HostConfig", {})
    security = host.get("SecurityOpt", []) or []
    ulimits = host.get("Ulimits", []) or []
    nofile = [limit for limit in ulimits if limit.get("Name") == "nofile"]
    return (config.get("User") == f"{uid}:{gid}" and
            config.get("Entrypoint") == entrypoint and config.get("Cmd") == command and
            host.get("NetworkMode") == network and host.get("ReadonlyRootfs") is True and
            host.get("Privileged") is False and (host.get("CapAdd") or []) == (
                ["CAP_NET_BIND_SERVICE"] if role == "zulip-caddy" else []) and
            "ALL" in (host.get("CapDrop") or []) and
            any(value.startswith("no-new-privileges") for value in security) and
            host.get("PidsLimit") == 64 and host.get("Memory") == 256 * 1024 * 1024 and
            host.get("NanoCpus") == 1_000_000_000 and len(nofile) == 1 and
            nofile[0].get("Soft") == 256 and nofile[0].get("Hard") == 256 and
            (config.get("Labels", {}) or {}).get("dev.codex.service-role") == role)


def zuliprc_mount_args(path: Path) -> list[str]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"Zulip credentials are missing: {path}") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ConfigError(f"Zulip credentials must be an unlinked regular file: {path}")
    if metadata.st_uid != os.getuid():
        raise ConfigError(f"Zulip credentials must be owned by uid {os.getuid()}: {path}")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ConfigError(f"Zulip credentials must have mode 0600: {path}")
    resolved = path.resolve(strict=True)
    if any(character in str(resolved) for character in (",", "\n", "\r")):
        raise ConfigError("Zulip credential path contains a container-mount delimiter")
    return [
        "--mount", f"type=bind,src={resolved},dst=/run/secrets/zuliprc,readonly",
    ]


COMMAND_PROXY_STATE_SCHEMA = 1


def _validate_codex_network_labels(auth: dict[str, Any], labels: dict[str, dict]) -> None:
    if any(labels[role].get("dev.codex.service-owner") != auth["service-owner"]
           or labels[role].get("dev.codex.credential-domain") != "codex"
           or labels[role].get("dev.codex.network-role") != role
           for role in ("application", "refresh")):
        raise ConfigError("active session authentication network ownership changed")


def _validate_codex_broker(owner, auth: dict[str, Any], image: str, uid: int, gid: int,
                           *, snapshot=None) -> None:
    try:
        kind, auth = parse_auth_record(auth)
    except ValueError as error:
        raise ConfigError("active session has invalid authentication service identity") from error
    if kind != "managed" or auth["runtime-owner"] != runtime_identity(owner):
        raise ConfigError("active session has invalid authentication service identity")
    helper = resolved_codex_broker_plan(Path(__file__).with_name("auth-proxy"), image, uid, gid)
    caddy = accepted_caddy_image(auth["caddy-image-chain"], owner)
    material = {"caddy": caddy.__dict__, "configuration": auth["configuration"]["digest"],
                "helper": helper.implementation_identity}
    expected = "sha256:" + hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (auth["image"] != caddy.runtime_reference or auth["caddy-image-chain"] != caddy.__dict__
            or auth["helper-implementation"] != helper.implementation_identity
            or auth["implementation-identity"] != expected):
        raise ConfigError("active session has invalid authentication service identity")
    live = snapshot if snapshot is not None else owner.inspect_container(auth["container"])
    helper_live = owner.inspect_container(auth["helper-container"])
    try:
        validate_configuration_mount(live, Path(auth["configuration"]["path"]),
                                     auth["configuration"]["digest"])
    except ValueError as error:
        raise ConfigError("active session Caddy configuration changed") from error
    networks = live.get("NetworkSettings", {}).get("Networks", {})
    helper_networks = owner.container_networks(helper_live)
    try:
        network_labels = {}
        for role in ("application", "refresh"):
            inspected = owner.run(["network", "inspect", auth["networks"][role]],
                                  capture_output=True)
            network = json.loads(inspected.stdout)[0]
            network_labels[role] = network.get(
                "Labels", network.get("CNI", {}).get("nerdctlLabels", {})) or {}
    except (KeyError, ValueError, subprocess.SubprocessError) as error:
        raise ConfigError("active session authentication network inspection failed") from error
    _validate_codex_network_labels(auth, network_labels)
    mounts = [mount for mount in helper_live.get("Mounts", [])
              if mount.get("Destination") == "/var/lib/codex-auth"]
    caddy_credentials = [mount for mount in live.get("Mounts", [])
                         if mount.get("Destination") == "/var/lib/codex-auth"]
    caddy_sockets = [mount for mount in live.get("Mounts", [])
                     if mount.get("Destination") == "/run/profile-helper"]
    helper_sockets = [mount for mount in helper_live.get("Mounts", [])
                      if mount.get("Destination") == "/run/profile-helper"]
    if (set(networks) != {auth["networks"]["agent-link"], auth["networks"]["application"]}
            or set(helper_networks) != {auth["networks"]["refresh"]}
            or caddy_credentials or len(mounts) != 1 or mounts[0].get("RW") is not True
            or len(caddy_sockets) != 1 or caddy_sockets[0].get("Name") != auth["socket-volume"]
            or caddy_sockets[0].get("RW") is not False
            or len(helper_sockets) != 1 or helper_sockets[0].get("Name") != auth["socket-volume"]
            or helper_sockets[0].get("RW") is not True):
        raise ConfigError("active session authentication network or credential mount changed")
    source = mounts[0].get("Source")
    try:
        source_identity = credential_source_identity(Path(source)) if isinstance(source, str) else None
    except (OSError, ValueError) as error:
        raise ConfigError("active session authentication credential source changed") from error
    if source_identity != auth["credential-volume"]["identity"]:
        raise ConfigError("active session authentication credential source changed")
    inspection = {"snapshot": live}
    verified = owner.inspect_image(auth["image"])
    helper_verified = owner.inspect_image(image)
    if not owner.container_matches_image(auth["container"], verified, **inspection, labels={
            "dev.codex.service-owner": auth["service-owner"],
            "dev.codex.credential-domain": "codex",
    }) or not owner.container_matches_image(auth["helper-container"], helper_verified,
            snapshot=helper_live, labels={"dev.codex.service-owner": auth["service-owner"],
                                          "dev.codex.credential-domain": "codex"}):
        raise ConfigError("active session has an unhealthy authentication service")
    ready = owner.run(["exec", auth["container"], "wget", "-q", "-O", "/dev/null",
                       "http://127.0.0.1:8787/ready"],
                      check=False, capture_output=True)
    if ready.returncode:
        raise ConfigError("active session authentication service is not locally ready")
_ADAPTER_BEGIN = b"\n# BEGIN OWNED COMMAND PROXY ADAPTER\n"
_ADAPTER_END = b"\n# END OWNED COMMAND PROXY ADAPTER\n"


def _command_proxy_adapter_bytes(source: bytes | None = None) -> bytes:
    """Hash the owned implementation region plus its forwarding implementation."""
    source = Path(__file__).read_bytes() if source is None else source
    try:
        owned = source.split(_ADAPTER_BEGIN, 1)[1].split(_ADAPTER_END, 1)[0]
    except IndexError as error:
        raise ConfigError("command proxy adapter source boundary is missing") from error
    lima = Path(__file__).with_name("lima")
    return owned + b"\0" + b"\0".join(
        path.read_bytes() for path in (lima / "proxy_forward.py", lima / "proxy_socket.py")
    )


# BEGIN OWNED COMMAND PROXY ADAPTER


def _command_proxy_resolved(name: str, command: dict[str, Any], image: str,
                            network: str, uid: int, gid: int):
    adapter_bytes = _command_proxy_adapter_bytes()
    plan = ServicePlan(
        role=name, family=ServiceFamily.COMMAND_PROXY, scope=ServiceScope.SHARED_SESSION,
        adapter="command-proxy", adapter_identity="sha256:" + hashlib.sha256(adapter_bytes).hexdigest(),
        state_schema=COMMAND_PROXY_STATE_SCHEMA, image_role="proxy", image_uid=uid, image_gid=gid,
        fixed_parameters={"command": command, "network": network},
    )
    return plan.resolve(adapter_bytes=adapter_bytes, image=_proxy_image_reference(image))


def _proxy_image_reference(image: str) -> str:
    """Normalize the runtime-verified digest for lifecycle identity hashing."""
    if "@sha256:" in image:
        return image
    if image.startswith("sha256:") and len(image) == 71:
        return "command-proxy@" + image
    raise ConfigError("proxy image is not an immutable verified reference")


def _proxy_resource_identity(kind: str, owner: str) -> str:
    return f"{kind}:{owner}"


def _recorded_effect(proxy: dict[str, Any], status: str, persist, cancelled,
                     operation, service: str) -> None:
    """Durably bracket an effect whose failure cannot prove non-publication."""
    proxy["resource-status"][status] = "intended"; persist()
    try:
        operation()
    except BaseException:
        proxy["resource-status"][status] = "unknown"; persist()
        raise
    proxy["resource-status"][status] = "created"; persist()
    if cancelled is not None and cancelled.is_set():
        raise ConfigError(f"proxy {service} startup cancelled")


class CommandProxyHandle:
    """Runtime lifecycle and resources for one ordinary command-proxy start."""

    def __init__(self, lifecycle: ServiceLifecycle, registry: ResourceRegistry,
                 record: dict[str, Any]) -> None:
        self.lifecycle = lifecycle
        self.registry = registry
        self.record = record

    def cleanup(self) -> None:
        result = self.registry.cleanup(0)
        if result.remaining:
            failures = ", ".join(f"{item.identity}={item.code}" for item in result.failures)
            raise ConfigError(
                "recorded proxy resources remain after cleanup; retaining recovery metadata: "
                + ", ".join(result.remaining) + (f" ({failures})" if failures else "")
                + f"; recovery: {RECOVERY_COMMAND}"
            )
        for diagnostic in self.registry.adapter_diagnostics:
            print(f"Sandbox proxy cleanup: {diagnostic}", file=sys.stderr)


def proxy_container_identity(name: str, uid: int | None, gid: int | None) -> tuple[int | None, int | None]:
    # macOS VZ presents private host binds to rootless container root. Linux
    # uidmapped virtiofs presents them to the agent UID instead.
    mapped = (OUTER_RUNTIME.provider == "lima-docker" and
              OUTER_RUNTIME.record.get("virtiofs_map") is not None)
    return (0, 0) if name == "jj" and not mapped else (uid, gid)


def start_one_proxy(
    args: argparse.Namespace, repo: Path, identity: str, images: dict[str, str],
    state: dict[str, Any], state_lock: threading.Lock, name: str, command: dict[str, Any],
    *, owners: OwnerSet | None = None, cancelled: threading.Event | None = None,
    handles: list[Any] | None = None,
) -> dict[str, str]:
    service_owner = uuid.uuid4().hex
    container_uid, container_gid = proxy_container_identity(name, os.getuid(), os.getgid())
    selected_network = args.network if command["network"] else "none"
    zulip_network = f"{args.prefix}-zulip-application" if name == "zulip" else None
    zulip_pair = None
    if zulip_network:
        helper_image = getattr(args, "helper_image", None)
        if not args.zuliprc or not helper_image:
            raise ConfigError("trusted Zulip proxy requires credentials and a helper image")
        selected_network = zulip_network
        resolved = resolved_zulip_broker_plan(
            Path(__file__).parents[1] / "zulip-proxy",
            Path(__file__).with_name("auth-proxy") / "typed_broker.py",
            images[name], os.getuid(), os.getgid(), selected_network,
        )
        helper = resolved_zulip_helper_plan(Path(__file__).with_name("auth-proxy"),
                                            helper_image, os.getuid(), os.getgid())
        caddy_identity = resolve_caddy_image(OUTER_RUNTIME)
        upstream = zulip_site(Path(args.zuliprc))
        pair_token = uuid.uuid4().hex + "." + uuid.uuid4().hex + "." + uuid.uuid4().hex
        caddy_name = f"{args.prefix}-zulip-caddy"
        helper_name = f"{args.prefix}-zulip-helper"
        socket_name = f"{args.prefix}-zulip-helper-socket"
        config_path = runtime_directory(repo) / (caddy_name + ".json")
        config_bytes = generate_caddy_config("zulip", upstream, token=pair_token)
        config_digest = caddy_configuration_digest(config_bytes)
        zulip_pair = EgressPairPlan(
            domain="zulip", service_owner=service_owner, caddy_name=caddy_name,
            helper_name=helper_name, socket_volume=socket_name,
            configuration_path=config_path, configuration=config_bytes,
            caddy_image=caddy_identity, helper_image=helper_image,
            uid=os.getuid(), gid=os.getgid(),
            application_network=zulip_network, helper_network="none",
            public_networks=(("network", "application", zulip_network),),
            helper_mounts=(zuliprc_mount_args(Path(args.zuliprc))[1],),
            helper_environment=("ZULIPRC=/run/secrets/zuliprc",
                                f"CADDY_PROFILE_TOKEN={pair_token}"),
            helper_arguments=("--profile", "zulip"),
        )
        pair_identity = zulip_pair.implementation_identity(helper.implementation_identity)
    else:
        resolved = _command_proxy_resolved(
            name, command, images[name], selected_network, container_uid, container_gid,
        )
    lifecycle = ServiceLifecycle(resolved, service_owner, owners or OwnerSet())
    lifecycle.transition(LifecycleState.RESOLVED)
    lifecycle.transition(LifecycleState.PREPARING)
    lifecycle.transition(LifecycleState.STARTING)

    volume = f"{args.prefix}-{name}"
    container = f"{args.prefix}-{name}"
    proxy = {
        "name": name, "volume": volume, "container": container, "image": images[name],
        "service-owner": service_owner, "implementation-identity": resolved.implementation_identity,
        "state-schema": COMMAND_PROXY_STATE_SCHEMA, "lifecycle-state": "starting",
        "identity-parameters": {"uid": container_uid, "gid": container_gid, "network": selected_network},
        "resource-status": {"volume": "intended", "container": "intended", "forward": "absent"},
    }
    if isinstance(OUTER_RUNTIME, VMRuntime):
        proxy["volume-owner"] = service_owner
    if zulip_network:
        pair_plan = zulip_pair
        proxy.update({
            "family": "authenticated-egress", "credential-domain": "zulip",
            "network": zulip_network, "network-owner": service_owner,
            "session-token": uuid.uuid4().hex + "." + uuid.uuid4().hex + "." + uuid.uuid4().hex,
            "credential-mount": "/run/secrets/zuliprc", "mutable-state": "none",
            "network-policy": OUTER_RUNTIME.public_network_policy_identity(),
            "endpoint": {"container": container, "socket": "/run/sandbox-proxy/socket"},
            "caddy-container": pair_plan.caddy_name, "helper-container": pair_plan.helper_name,
            "socket-volume": pair_plan.socket_volume, "pair-token": pair_token,
            "caddy-image-chain": pair_plan.caddy_image.__dict__,
            "configuration": {"path": str(config_path), "digest": config_digest},
            "helper-image": helper_image, "helper-implementation": helper.implementation_identity,
            "pair-implementation": pair_identity,
            "credential-identity": zulip_credential_identity(Path(args.zuliprc)),
            "credential-source": str(Path(args.zuliprc).resolve(strict=True)),
            "networks": {"application": zulip_network},
        })
        proxy["resource-status"].update({"network": "intended", "socket-volume": "intended",
            "helper-container": "intended", "caddy-container": "intended", "configuration": "intended"})

    def persist() -> None:
        with state_lock:
            write_atomic(Path(args.state), json.dumps(state))

    # This single schema-3 proxy record is both endpoint projection and recovery
    # authority. It is registered before any effect that can partially succeed.
    with state_lock:
        state["proxies"].append(proxy)
        write_atomic(Path(args.state), json.dumps(state))
    registry = _proxy_registry(OUTER_RUNTIME, proxy)
    handle = CommandProxyHandle(lifecycle, registry, proxy)
    if handles is not None:
        with state_lock:
            handles.append(handle)
    try:
        if cancelled is not None and cancelled.is_set():
            raise ConfigError(f"proxy {name} startup cancelled")
        if zulip_network:
            pair_effect = lambda status, operation: _recorded_effect(
                proxy, status, persist, cancelled, operation, name)
            start_egress_pair(
                OUTER_RUNTIME, zulip_pair, pair_effect,
                cancelled=lambda: cancelled is not None and cancelled.is_set(),
                error=ConfigError, logs=proxy_logs,
            )
        proxy["resource-status"]["volume"] = "intended"; persist()
        try:
            if isinstance(OUTER_RUNTIME, VMRuntime):
                OUTER_RUNTIME.initialize_volume(volume, container_uid, container_gid, proxy["volume-owner"])
            else:
                _docker("volume", "create", "--uid", str(container_uid), "--gid", str(container_gid),
                        "--label", f"dev.codex.service-owner={service_owner}", volume)
        except BaseException:
            proxy["resource-status"]["volume"] = "unknown"; persist(); raise
        proxy["resource-status"]["volume"] = "created"; persist()
        if cancelled is not None and cancelled.is_set():
            raise ConfigError(f"proxy {name} startup cancelled")
        if cancelled is not None and cancelled.is_set():
            raise ConfigError(f"proxy {name} startup cancelled")
        container_repo = container_repository(args.container_repo)
        docker_args = [
            "run", "--detach", "--name", container, "--cap-drop=ALL",
            "--label", "dev.codex.sandbox-proxy=true",
            "--label", f"dev.codex.repository={identity}",
            "--label", f"dev.codex.command={name}",
            "--label", f"dev.codex.service-owner={service_owner}",
            "--security-opt=no-new-privileges", "--read-only",
            "--user", f"{container_uid}:{container_gid}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--network", selected_network,
            "--pids-limit", "96", "--memory", "2304m", "--cpus", "2",
            "--ulimit", "nofile=1024:1024", "--workdir", str(container_repo / command["workdir"]),
            "--entrypoint", command["argv"][0],
            "--env", "SANDBOX_PROXY_SOCKET=/run/sandbox-proxy/socket",
            "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxy",
        ]
        if isinstance(OUTER_RUNTIME, VMRuntime) and command["network"]:
            network = json.loads((OUTER_RUNTIME.host.state / "source/rootless-network.json").read_text())
            docker_args += ["--dns", network["dns"]]
        if name == "jj":
            git_dir, common_dir = git_metadata_paths(repo)
            jj_repo = jj_repository_path(repo)
            docker_args += [
                "--env", f"JJ_PROXY_REPO={container_repo}",
                "--env", f"JJ_PROXY_GIT_DIR={metadata_container_path(repo, git_dir, container_repo)}",
                "--env", f"JJ_PROXY_COMMON_DIR={metadata_container_path(repo, common_dir, container_repo)}",
                "--env", f"JJ_PROXY_JJ_REPO={metadata_container_path(repo, jj_repo, container_repo)}",
            ]
        docker_args += proxy_git_environment_args(repo, container_repo, command)
        if name == "zulip":
            docker_args += [
                "--label", "dev.codex.credential-domain=zulip",
                "--env", f"ZULIP_BROKER_KEY={proxy['session-token']}",
                "--env", f"ZULIP_CADDY_ENDPOINT=http://{proxy['caddy-container']}:8787/api/v1/messages",
            ]
        checked_repository_path(repo, command["workdir"], f"command {name} workdir")
        docker_args += proxy_repository_mount_args(repo, container_repo, name, command)
        docker_args += [images[name], *command["argv"][1:]]
        proxy["resource-status"]["container"] = "intended"; persist()
        try: _docker(*docker_args)
        except BaseException:
            proxy["resource-status"]["container"] = "unknown"; persist(); raise
        proxy["resource-status"]["container"] = "created"; persist()
        if cancelled is not None and cancelled.is_set():
            raise ConfigError(f"proxy {name} startup cancelled")
        if OUTER_RUNTIME.provider == "lima-docker":
            forwarding = OUTER_RUNTIME.proxy_forward_record(container, proxy["volume-owner"])
            if forwarding.get("owner") != service_owner:
                raise ConfigError("proxy forwarding owner changed before registration")
            registry.register(OwnedResource(
                _proxy_resource_identity("forward", service_owner), service_owner,
                lambda: ResourcePresence.OWNED,
                lambda: OUTER_RUNTIME.stop_proxy_forward(forwarding),
                (_proxy_resource_identity("container", service_owner),),
            ))
            # Recovery authority precedes both host and guest alias publication.
            proxy["forwarding"] = forwarding
            proxy["resource-status"]["forward"] = "intended"
            persist()
            try: OUTER_RUNTIME.start_proxy_forward(forwarding)
            except BaseException:
                proxy["resource-status"]["forward"] = "unknown"; persist(); raise
            proxy["resource-status"]["forward"] = "created"; persist()
            if cancelled is not None and cancelled.is_set():
                raise ConfigError(f"proxy {name} startup cancelled")
        deadline = time.monotonic() + 10
        readiness_error = ""
        while (remaining := deadline - time.monotonic()) > 0:
            if cancelled is not None and cancelled.is_set():
                raise ConfigError(f"proxy {name} startup cancelled")
            check = subprocess.run(
                OUTER_RUNTIME.argv(["exec", *([] if OUTER_RUNTIME.provider == "lima" else ["--interactive"]),
                                    container, "/trusted/bin/sandbox-proxy-forward",
                                    *(["--health"] if name == "zulip" else [])]),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True, timeout=remaining,
            )
            readiness_error = check.stderr.strip()
            if check.returncode == 0:
                lifecycle.transition(LifecycleState.READY)
                proxy["lifecycle-state"] = "ready"
                persist()
                return proxy
            status = _docker("inspect", "--format", "{{.State.Running}}", container, capture=True).stdout.strip()
            if status != "true":
                logs = proxy_logs(container)
                detail = f":\n{logs}" if logs else ""
                raise ConfigError(f"proxy {name} exited before becoming ready{detail}")
            time.sleep(0.1)
        logs = proxy_logs(container)
        diagnostics = "\n".join(dict.fromkeys(output for output in (logs, readiness_error) if output))
        detail = f":\n{diagnostics}" if diagnostics else ""
        raise ConfigError(f"proxy {name} did not become ready{detail}")
    except BaseException:
        lifecycle.transition(LifecycleState.FAILED)
        proxy["lifecycle-state"] = "failed"
        persist()
        raise

# END OWNED COMMAND PROXY ADAPTER


def start_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest = load_manifest_file(Path(args.manifest))
    images = resolve_images(repo, manifest, getattr(args, 'images', None))
    state: dict[str, Any] = {"proxies": [], "runtime": runtime_identity(OUTER_RUNTIME)}
    if getattr(args, "agent_image", None) is not None:
        state["accepted"] = {
            "source-present": args.source_present,
            "agent-image": args.agent_image,
            "helper-image": args.helper_image,
            "parameters": {"uid": args.uid, "gid": args.gid},
            "proxy-images": images,
        }
    identity = repository_identity(repo)
    write_atomic(Path(args.state), json.dumps(state))
    state_lock = threading.Lock()
    owners = OwnerSet()
    cancelled = threading.Event()
    handles: list[CommandProxyHandle] = []
    executor = ThreadPoolExecutor(max_workers=max(1, len(manifest["commands"])))
    futures = [
        executor.submit(
            start_one_proxy, args, repo, identity, images, state, state_lock, name, command,
            owners=owners, cancelled=cancelled, handles=handles,
        )
        for name, command in manifest["commands"].items()
    ]
    try:
        for future in as_completed(futures):
            future.result()
        return 0
    except BaseException as startup_error:
        cancelled.set()
        for future in futures:
            future.cancel()
        # Running adapters are joined before cleanup, so they cannot create a
        # resource after recovery starts. Preserve the first startup failure.
        for future in futures:
            try:
                future.result()
            except BaseException:
                pass
        try:
            cleanup_failures = []
            with ThreadPoolExecutor(max_workers=max(1, len(handles))) as cleanup_workers:
                cleanup_work = [cleanup_workers.submit(handle.cleanup) for handle in handles]
                for cleanup in cleanup_work:
                    try:
                        cleanup.result()
                    except BaseException as error:
                        cleanup_failures.append(str(error))
            if cleanup_failures:
                raise ConfigError("; ".join(cleanup_failures))
        except BaseException as cleanup_error:
            # The state file remains the recovery authority. Cleanup diagnostics
            # must not replace the service-start failure seen by the launcher.
            startup_error.add_note(
                f"proxy cleanup failed; retaining recovery metadata: {cleanup_error}"
            )
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def _stop_legacy_state(state: dict[str, Any], owner=None) -> None:
    owner = owner or state_runtime(state, recovery=True)
    started = time.monotonic()
    containers = []
    auth = state.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("container"), str):
        containers.append(auth["container"])
    proxies = list(reversed([
        *state.get("proxies", []), *state.get("retired-proxies", []),
    ]))
    for proxy in proxies:
        if 'forwarding' in proxy:
            if owner.provider != 'lima-docker' or proxy['forwarding']['owner'] != proxy.get('volume-owner'):
                raise ConfigError('proxy forwarding recovery owner changed')
            owner.stop_proxy_forward(proxy['forwarding'])
    containers.extend(proxy["container"] for proxy in proxies)

    def discard(arguments: list[str]) -> subprocess.CompletedProcess:
        return owner.run(arguments[1:], check=False, capture_output=True)

    def report_remaining(kind, names, results, remaining):
        survivors = set(names).intersection(remaining)
        if not survivors:
            return
        details = []
        for name, result in zip(names, results):
            if name in survivors:
                reason = (result.stderr or "").strip() or f"removal exited {result.returncode} without a diagnostic"
                details.append(f"  {name}: {reason}")
        raise ConfigError(
            f"recorded {kind} remain after cleanup; retaining recovery metadata:\n"
            + "\n".join(details)
            + f"\nrecovery: {RECOVERY_COMMAND}"
        )

    # Podman's forced removal waits for the container stop timeout. Send SIGKILL
    # explicitly, then remove independent containers concurrently.
    with ThreadPoolExecutor(max_workers=max(1, len(containers))) as executor:
        list(executor.map(lambda container: discard(["docker", "kill", container]), containers))
    with ThreadPoolExecutor(max_workers=max(1, len(containers))) as executor:
        results = list(executor.map(lambda container: discard(["docker", "rm", container]), containers))
    if containers:
        remaining = [name for name in containers
                     if resource_exists(owner, ResourceKind.CONTAINER, name)]
        report_remaining("containers", containers, results, remaining)
    if os.environ.get("CODEX_SANDBOX_TIMING"):
        print(f"Sandbox proxy cleanup: containers={time.monotonic() - started:.2f}s", file=sys.stderr)
    volumes_started = time.monotonic()
    volumes = sorted(set(proxy["volume"] for proxy in proxies))
    for proxy in proxies:
        if "volume-owner" in proxy:
            presence = resource_presence(
                owner, ResourceKind.VOLUME, proxy["volume"], proxy["volume-owner"],
                authority=ResourceOwnerAuthority.VOLUME_CREATOR,
            )
            if presence is ResourcePresence.MISMATCHED:
                raise ConfigError("volume belongs to another creator; retaining recovery metadata")
    with ThreadPoolExecutor(max_workers=max(1, len(volumes))) as executor:
        results = list(executor.map(lambda volume: discard(["docker", "volume", "rm", volume]), volumes))
    if volumes:
        remaining = [name for name in volumes
                     if resource_exists(owner, ResourceKind.VOLUME, name)]
        report_remaining("volumes", volumes, results, remaining)
    if os.environ.get("CODEX_SANDBOX_TIMING"):
        print(f"Sandbox proxy cleanup: volumes={time.monotonic() - volumes_started:.2f}s", file=sys.stderr)



_MANAGED_PROXY_REQUIRED = {
    "name", "volume", "container", "image", "service-owner", "implementation-identity",
    "state-schema", "lifecycle-state", "identity-parameters", "resource-status",
}
_MANAGED_PROXY_OPTIONAL = {
    "volume-owner", "forwarding", "family", "credential-domain", "network",
    "network-owner", "network-policy", "session-token", "credential-mount", "mutable-state",
    "endpoint", "caddy-container", "helper-container", "socket-volume", "pair-token",
    "caddy-image-chain", "configuration", "helper-image", "helper-implementation",
    "pair-implementation", "credential-identity", "credential-source", "networks",
}


def _managed_proxy_record(proxy: Any) -> dict[str, Any] | None:
    """Parse a managed record; records without service-owner are explicit legacy schema 3."""
    if not isinstance(proxy, dict):
        raise ConfigError("proxy recovery record must be an object")
    if "service-owner" not in proxy:
        return None
    if set(proxy) - (_MANAGED_PROXY_REQUIRED | _MANAGED_PROXY_OPTIONAL) or not _MANAGED_PROXY_REQUIRED <= set(proxy):
        raise ConfigError("managed proxy recovery record has invalid fields")
    owner = proxy["service-owner"]
    parameters = proxy["identity-parameters"]
    statuses = proxy["resource-status"]
    if (not isinstance(owner, str) or re.fullmatch(r"[0-9a-f]{32}", owner) is None or
            not isinstance(proxy["implementation-identity"], str) or
            IMAGE_RE.fullmatch(proxy["implementation-identity"]) is None or
            proxy["state-schema"] != COMMAND_PROXY_STATE_SCHEMA or
            proxy["lifecycle-state"] not in {"starting", "ready", "failed"} or
            not isinstance(parameters, dict) or set(parameters) != {"uid", "gid", "network"} or
            not isinstance(parameters["uid"], int) or not isinstance(parameters["gid"], int) or
            not isinstance(parameters["network"], str) or not parameters["network"] or
            not isinstance(statuses, dict) or set(statuses) not in (
                {"volume", "container", "forward"},
                {"volume", "container", "forward", "network"},
                {"volume", "container", "forward", "network", "socket-volume",
                 "helper-container", "caddy-container", "configuration"}) or
            any(value not in ({"absent", "intended", "created", "unknown"}
                              if proxy.get("name") == "zulip" else
                              {"absent", "intended", "created"}) for value in statuses.values()) or
            any(not isinstance(proxy[field], str) or not proxy[field] for field in
                ("name", "volume", "container", "image"))):
        raise ConfigError("managed proxy recovery record is invalid")
    if proxy.get("volume-owner", owner) != owner:
        raise ConfigError("managed proxy volume owner changed")
    forwarding = proxy.get("forwarding")
    if forwarding is not None and (not isinstance(forwarding, dict) or forwarding.get("owner") != owner):
        raise ConfigError("managed proxy forwarding owner changed")
    if (forwarding is None) != (statuses["forward"] == "absent"):
        raise ConfigError("managed proxy forwarding status is inconsistent")
    if proxy["name"] == "zulip":
        required = {"family", "credential-domain", "network", "network-owner", "network-policy",
                    "session-token", "credential-mount", "mutable-state", "endpoint",
                    "caddy-container", "helper-container", "socket-volume", "pair-token",
                    "caddy-image-chain", "configuration", "helper-image", "helper-implementation",
                    "pair-implementation", "credential-identity", "credential-source", "networks"}
        if (not required <= set(proxy) or proxy["family"] != "authenticated-egress" or
                proxy["credential-domain"] != "zulip" or proxy["network-owner"] != owner or
                proxy["network"] != parameters["network"] or
                not IMAGE_RE.fullmatch(proxy["network-policy"]) or
                proxy["endpoint"] != {"container": proxy["container"],
                                      "socket": "/run/sandbox-proxy/socket"} or
                not isinstance(proxy["session-token"], str) or
                re.fullmatch(r"[0-9a-f]{32}\.[0-9a-f]{32}\.[0-9a-f]{32}", proxy["session-token"]) is None or
                proxy["credential-mount"] != "/run/secrets/zuliprc" or
                proxy["mutable-state"] != "none" or proxy["networks"] != {"application": proxy["network"]} or
                not all(isinstance(proxy.get(field), str) and proxy[field] for field in
                        ("caddy-container", "helper-container", "socket-volume", "helper-image",
                         "credential-source")) or not Path(proxy["credential-source"]).is_absolute() or
                not _TOKEN_RE.fullmatch(proxy.get("pair-token", "")) or
                not all(IMAGE_RE.fullmatch(proxy.get(field, "")) for field in
                        ("helper-implementation", "pair-implementation", "credential-identity")) or
                not isinstance(proxy.get("configuration"), dict) or
                set(proxy["configuration"]) != {"path", "digest"} or
                not IMAGE_RE.fullmatch(proxy["configuration"].get("digest", "")) or
                statuses.get("network") not in {"intended", "created", "unknown"}):
            raise ConfigError("managed Zulip broker recovery record is invalid")
    elif set(proxy) & {"family", "credential-domain", "network", "network-owner", "network-policy",
                       "session-token", "credential-mount", "mutable-state", "endpoint"}:
        raise ConfigError("non-Zulip proxy contains Zulip broker authority")
    return proxy


def _validate_proxy_implementation(proxy: dict[str, Any], command: dict[str, Any],
                                   *, uid: int | None = None, gid: int | None = None) -> None:
    managed = _managed_proxy_record(proxy)
    if managed is None:
        return
    parameters = managed["identity-parameters"]
    if managed["lifecycle-state"] != "ready":
        raise ConfigError("managed required proxy is not ready")
    expected_uid, expected_gid = proxy_container_identity(managed["name"], uid, gid)
    if (expected_uid is not None and parameters["uid"] != expected_uid or
            expected_gid is not None and parameters["gid"] != expected_gid):
        raise ConfigError("managed proxy UID/GID changed")
    if (command["network"] and parameters["network"] == "none") or (
            not command["network"] and parameters["network"] != "none"):
        raise ConfigError("managed proxy network changed")
    if managed["name"] == "zulip":
        expected = resolved_zulip_broker_plan(
            Path(__file__).parents[1] / "zulip-proxy",
            Path(__file__).with_name("auth-proxy") / "typed_broker.py",
            managed["image"], parameters["uid"], parameters["gid"], parameters["network"],
        ).implementation_identity
        helper = resolved_zulip_helper_plan(Path(__file__).with_name("auth-proxy"),
                                            managed["helper-image"], parameters["uid"], parameters["gid"])
        caddy = accepted_caddy_image(managed["caddy-image-chain"], OUTER_RUNTIME)
        material = {"caddy": caddy.__dict__, "configuration": managed["configuration"]["digest"],
                    "helper": helper.implementation_identity}
        pair = "sha256:" + hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (helper.implementation_identity != managed["helper-implementation"] or
                pair != managed["pair-implementation"]):
            raise ConfigError("managed Zulip pair implementation identity changed")
    else:
        expected = _command_proxy_resolved(
            managed["name"], command, managed["image"], parameters["network"],
            parameters["uid"], parameters["gid"],
        ).implementation_identity
    if expected != managed["implementation-identity"]:
        raise ConfigError(
            "managed proxy implementation identity changed; the existing proxy was "
            "built from different launcher code or configuration. Restart the sandbox "
            "session to rebuild it; do not edit the recovery record manually"
        )


def _proxy_registry(runtime, proxy: dict[str, Any]) -> ResourceRegistry:
    managed_record = _managed_proxy_record(proxy)
    service_owner = proxy.get("service-owner")
    managed = managed_record is not None
    if not managed:
        # Credential-free compatibility for records created before step 2.
        service_owner = hashlib.sha256(
            (str(proxy.get("container")) + "\0" + str(proxy.get("volume"))).encode()
        ).hexdigest()[:32]
    registry = ResourceRegistry(service_owner)
    adapter_diagnostics: list[str] = []
    registry.adapter_diagnostics = adapter_diagnostics
    volume_id = _proxy_resource_identity("volume", service_owner)
    container_id = _proxy_resource_identity("container", service_owner)
    proxy_roles = {"proxy-volume": ()}
    proxy_identities = {"proxy-volume": volume_id}
    container_dependencies = ["proxy-volume"]
    if "network" in proxy:
        proxy_roles["network"] = ()
        proxy_identities["network"] = _proxy_resource_identity("network", service_owner)
        container_dependencies.append("network")
    if proxy.get("name") == "zulip" and "caddy-container" in proxy:
        proxy_roles["caddy-container"] = ()
        proxy_identities["caddy-container"] = _proxy_resource_identity(
            "zulip-caddy", service_owner,
        )
        container_dependencies.append("caddy-container")
    proxy_roles["proxy-container"] = tuple(container_dependencies)
    proxy_identities["proxy-container"] = container_id
    if "forwarding" in proxy:
        proxy_roles["forward"] = ("proxy-container",)
        proxy_identities["forward"] = _proxy_resource_identity("forward", service_owner)
    proxy_dependencies = ResourceTopology(proxy_roles).bind(proxy_identities)

    def listed(kind: str, name: str) -> bool:
        return resource_exists(runtime, ResourceKind(kind), name)

    def volume_presence() -> ResourcePresence:
        if not listed("volume", proxy["volume"]):
            return ResourcePresence.ABSENT
        if managed:
            authority = (ResourceOwnerAuthority.VOLUME_CREATOR if "volume-owner" in proxy
                         else ResourceOwnerAuthority.SERVICE)
            return resource_presence(
                runtime, ResourceKind.VOLUME, proxy["volume"], service_owner,
                authority=authority,
            )
        elif "volume-owner" in proxy:
            return resource_presence(
                runtime, ResourceKind.VOLUME, proxy["volume"], proxy["volume-owner"],
                authority=ResourceOwnerAuthority.VOLUME_CREATOR,
            )
        return ResourcePresence.OWNED

    def container_presence() -> ResourcePresence:
        if not listed("container", proxy["container"]):
            return ResourcePresence.ABSENT
        if managed:
            return resource_presence(
                runtime, ResourceKind.CONTAINER, proxy["container"], service_owner,
            )
        return ResourcePresence.OWNED

    def remove(arguments: list[str]) -> None:
        result = runtime.run(arguments, check=False, capture_output=True)
        if result.returncode:
            diagnostic = f"{arguments[0]} {arguments[-1]} exited {result.returncode}"
            adapter_diagnostics.append(diagnostic)
            raise ConfigError(diagnostic)

    def remove_container() -> None:
        if managed:
            remove_owned_resource(
                runtime, ResourceKind.CONTAINER, proxy["container"], service_owner,
            )
            return
        killed = runtime.run(["kill", proxy["container"]], check=False, capture_output=True)
        removed = runtime.run(["rm", proxy["container"]], check=False, capture_output=True)
        operation_failures = []
        if killed.returncode:
            operation_failures.append(f"kill {proxy['container']} exited {killed.returncode}")
        if removed.returncode:
            operation_failures.append(f"rm {proxy['container']} exited {removed.returncode}")
        adapter_diagnostics.extend(operation_failures)
        # A failed kill is diagnostic only when rm establishes absence. Recovery
        # authority follows rm, not the preliminary signal attempt.
        if removed.returncode:
            raise ConfigError("; ".join(operation_failures))

    def remove_volume() -> None:
        if managed or "volume-owner" in proxy:
            expected_owner = service_owner if managed else proxy["volume-owner"]
            authority = (ResourceOwnerAuthority.VOLUME_CREATOR if "volume-owner" in proxy
                         else ResourceOwnerAuthority.SERVICE)
            remove_owned_resource(
                runtime, ResourceKind.VOLUME, proxy["volume"], expected_owner,
                authority=authority,
            )
            return
        remove(["volume", "rm", proxy["volume"]])

    registry.register(OwnedResource(
        volume_id, service_owner, volume_presence, remove_volume,
        proxy_dependencies[volume_id],
    ))
    network_id = proxy_identities.get("network")
    if network_id is not None:
        def network_presence() -> ResourcePresence:
            return resource_presence(
                runtime, ResourceKind.NETWORK, proxy["network"], service_owner,
            )
        registry.register(OwnedResource(
            network_id, service_owner, network_presence,
            lambda: remove_owned_resource(
                runtime, ResourceKind.NETWORK, proxy["network"], service_owner,
            ),
        ))
    if proxy.get("name") == "zulip" and "caddy-container" in proxy:
        socket_id = _proxy_resource_identity("zulip-socket", service_owner)
        helper_id = _proxy_resource_identity("zulip-helper", service_owner)
        caddy_id = _proxy_resource_identity("zulip-caddy", service_owner)
        config_id = _proxy_resource_identity("zulip-config", service_owner)
        pair_dependencies = egress_pair_topology(
            application_network_role="network",
        ).bind({
            "configuration": config_id,
            "socket-volume": socket_id,
            "network": network_id,
            "helper-container": helper_id,
            "caddy-container": caddy_id,
        })
        def named_presence(kind: str, name: str) -> ResourcePresence:
            return resource_presence(runtime, ResourceKind(kind), name, service_owner)
        def remove_named(kind: str, name: str) -> None:
            remove_owned_resource(runtime, ResourceKind(kind), name, service_owner)
        path = Path(proxy["configuration"]["path"])
        def config_presence() -> ResourcePresence:
            try: digest = caddy_configuration_digest(path.read_bytes())
            except FileNotFoundError: return ResourcePresence.ABSENT
            return ResourcePresence.OWNED if digest == proxy["configuration"]["digest"] else ResourcePresence.MISMATCHED
        def remove_config() -> None:
            path.unlink(missing_ok=True)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        registry.register(OwnedResource(
            config_id, service_owner, config_presence, remove_config,
            pair_dependencies[config_id],
        ))
        registry.register(OwnedResource(socket_id, service_owner,
            lambda: named_presence("volume", proxy["socket-volume"]),
            lambda: remove_named("volume", proxy["socket-volume"]),
            pair_dependencies[socket_id]))
        registry.register(OwnedResource(helper_id, service_owner,
            lambda: named_presence("container", proxy["helper-container"]),
            lambda: remove_named("container", proxy["helper-container"]),
            pair_dependencies[helper_id]))
        registry.register(OwnedResource(caddy_id, service_owner,
            lambda: named_presence("container", proxy["caddy-container"]),
            lambda: remove_named("container", proxy["caddy-container"]),
            pair_dependencies[caddy_id]))
    registry.register(OwnedResource(
        container_id, service_owner, container_presence, remove_container,
        proxy_dependencies[container_id],
    ))
    forwarding = proxy.get("forwarding")
    if forwarding is not None:
        if runtime.provider != "lima-docker" or not isinstance(forwarding, dict):
            raise ConfigError("proxy forwarding recovery owner changed")
        if managed:
            forwarding_owned = (forwarding.get("owner") == service_owner
                                and proxy.get("volume-owner") == service_owner)
        else:
            forwarding_owned = (isinstance(proxy.get("volume-owner"), str)
                                and forwarding.get("owner") == proxy["volume-owner"])
        if not forwarding_owned:
            raise ConfigError("proxy forwarding recovery owner changed")
        registry.register(OwnedResource(
            _proxy_resource_identity("forward", service_owner), service_owner,
            lambda: ResourcePresence.OWNED,
            lambda: runtime.stop_proxy_forward(forwarding),
            proxy_dependencies[_proxy_resource_identity("forward", service_owner)],
        ))
    return registry


def _cleanup_proxy_service(runtime, proxy: dict[str, Any]) -> None:
    registry = _proxy_registry(runtime, proxy)
    result = registry.cleanup(0)
    if result.remaining:
        failures = ", ".join(f"{item.identity}={item.code}" for item in result.failures)
        raise ConfigError(
            "recorded proxy resources remain after cleanup; retaining recovery metadata: "
            + ", ".join(result.remaining) + (f" ({failures})" if failures else "")
            + f"; recovery: {RECOVERY_COMMAND}"
        )
    for diagnostic in registry.adapter_diagnostics:
        print(f"Sandbox proxy cleanup: {diagnostic}", file=sys.stderr)


def stop_state(state: dict[str, Any]) -> None:
    all_proxies = [*state.get("proxies", []), *state.get("retired-proxies", [])]
    lifecycle_schema = state.get("trusted-services")
    if lifecycle_schema not in (None, SESSION_LIFECYCLE_SCHEMA):
        raise ConfigError("invalid trusted-service recovery schema")
    auth = state.get("auth")
    managed_auth = False
    pair_auth = False
    if auth is not None:
        try:
            auth_kind, auth = parse_auth_record(
                auth, managed_required=lifecycle_schema == SESSION_LIFECYCLE_SCHEMA)
        except ValueError as error:
            raise ConfigError("invalid authentication recovery authority") from error
        managed_auth = auth_kind in {"managed", "managed-single"}
        pair_auth = auth_kind == "managed"
    # Validate recorded ownership before opening the runtime. A mismatched
    # recovery record must not trigger any backend interaction.
    for proxy in all_proxies:
        _managed_proxy_record(proxy)
    owner = state_runtime(state, recovery=True)
    if (not managed_auth and
            not any(isinstance(proxy, dict) and "service-owner" in proxy for proxy in all_proxies)):
        removed = remove_stopped_sandbox_holders(
            owner, recorded_proxy_volumes(state),
        )
        for container in removed:
            print(f"Sandbox proxy cleanup: removed stopped agent container {container}",
                  file=sys.stderr)
        _stop_legacy_state(state, owner)
        return
    proxies = list(reversed(all_proxies))
    seen: set[str] = set()
    for proxy in proxies:
        managed = _managed_proxy_record(proxy)
        if managed is not None:
            service_owner = managed["service-owner"]
            if service_owner in seen:
                raise ConfigError("trusted service recovery owner was reused")
            seen.add(service_owner)
    removed = remove_stopped_sandbox_holders(owner, recorded_proxy_volumes(state))
    for container in removed:
        print(f"Sandbox proxy cleanup: removed stopped agent container {container}",
              file=sys.stderr)
    # Independent service registries clean concurrently; the executor is joined
    # before returning or surfacing any failure.
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, len(proxies))) as executor:
        work = [(proxy, executor.submit(_cleanup_proxy_service, owner, proxy)) for proxy in proxies]
        for proxy, future in work:
            try:
                future.result()
            except Exception as error:
                failures.append(f"{proxy.get('name', 'unknown')}: {error}")
    auth = state.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("container"), str):
        auth_container = auth["container"]
        if pair_auth:
            service_owner = auth["service-owner"]
            auth["lifecycle-state"] = "stopping"
            registry = ResourceRegistry(service_owner)
            names = {"container": [auth["container"], auth["helper-container"]],
                     "network": [auth["networks"]["application"], auth["networks"]["refresh"]],
                     "volume": [auth["socket-volume"]]}

            def owned_presence(kind: str, name: str) -> ResourcePresence:
                return resource_presence(owner, ResourceKind(kind), name, service_owner)
            def resource_remove(kind: str, name: str) -> None:
                remove_owned_resource(owner, ResourceKind(kind), name, service_owner)

            config_id = "file:caddy-config"
            config_path = Path(auth["configuration"]["path"])
            def config_presence() -> ResourcePresence:
                try:
                    from caddy_foundation import configuration_digest
                    return (ResourcePresence.OWNED
                            if configuration_digest(config_path.read_bytes()) == auth["configuration"]["digest"]
                            else ResourcePresence.MISMATCHED)
                except FileNotFoundError:
                    return ResourcePresence.ABSENT
            def remove_config() -> None:
                config_path.unlink(missing_ok=True)
                descriptor = os.open(config_path.parent, os.O_DIRECTORY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
            registry.register(OwnedResource(config_id, service_owner, config_presence, remove_config))
            volume_id = f"volume:{auth['socket-volume']}"
            app_id = f"network:{auth['networks']['application']}"
            refresh_id = f"network:{auth['networks']['refresh']}"
            helper_id = f"container:{auth['helper-container']}"
            caddy_id = f"container:{auth['container']}"
            pair_dependencies = egress_pair_topology(
                application_network_role="application-network",
                helper_network_role="refresh-network",
            ).bind({
                "configuration": config_id,
                "socket-volume": volume_id,
                "application-network": app_id,
                "refresh-network": refresh_id,
                "helper-container": helper_id,
                "caddy-container": caddy_id,
            })
            for kind, name in (("volume", auth["socket-volume"]),
                               ("network", auth["networks"]["application"]),
                               ("network", auth["networks"]["refresh"])):
                identity = f"{kind}:{name}"
                registry.register(OwnedResource(identity, service_owner,
                    lambda k=kind,n=name: owned_presence(k,n),
                    lambda k=kind,n=name: resource_remove(k,n), pair_dependencies[identity]))
            registry.register(OwnedResource(helper_id, service_owner,
                lambda: owned_presence("container", auth["helper-container"]),
                lambda: resource_remove("container", auth["helper-container"]),
                pair_dependencies[helper_id]))
            registry.register(OwnedResource(caddy_id, service_owner,
                lambda: owned_presence("container", auth["container"]),
                lambda: resource_remove("container", auth["container"]),
                pair_dependencies[caddy_id]))
            result = registry.cleanup(0)
            if result.remaining:
                auth["lifecycle-state"] = "cleanup-failed"
                details = ", ".join(
                    f"{failure.identity}={failure.code}" for failure in result.failures
                )
                failures.append(
                    "authentication pair owner validation or removal failed; resources remain: "
                    + ", ".join(result.remaining)
                    + (f" ({details})" if details else "")
                )
            else:
                auth["lifecycle-state"] = "removed"
                auth["resource-status"] = {key: "removed" for key in auth["resource-status"]}
        elif managed_auth:
            # Stale pre-pair managed records are accepted only as owner-checked
            # recovery authority; active publication and joins reject them.
            service_owner = auth["service-owner"]
            try:
                presence = resource_presence(
                    owner, ResourceKind.CONTAINER, auth_container, service_owner,
                )
                if presence is ResourcePresence.MISMATCHED:
                    failures.append("authentication container owner validation failed")
                elif presence is ResourcePresence.OWNED:
                    remove_owned_resource(
                        owner, ResourceKind.CONTAINER, auth_container, service_owner,
                    )
            except (OSError, ValueError, subprocess.SubprocessError):
                failures.append("authentication container removal failed")
        else:
            if resource_exists(owner, ResourceKind.CONTAINER, auth_container):
                owner.run(["kill", auth_container], check=False, capture_output=True)
                if owner.run(["rm", auth_container], check=False, capture_output=True).returncode:
                    failures.append("authentication container removal failed")
    if failures:
        raise ConfigError("cleanup failed; retaining recovery metadata:\n" + "\n".join(failures))

def stop_main(args: argparse.Namespace) -> int:
    path = Path(args.state)
    if path.exists():
        contents = path.read_text(encoding="utf-8")
        if contents.strip():
            state = json.loads(contents)
            try:
                stop_state(state)
            except BaseException:
                if state.get("trusted-services") == SESSION_LIFECYCLE_SCHEMA:
                    write_atomic(path, json.dumps(state, sort_keys=True))
                raise
    return 0


def validate_live_proxies(owner, proxies, repository, *, snapshots=None, commands=None,
                          uid=None, gid=None):
    # Bound SSH concurrency and join every inspection before publication or
    # failure recovery can change the containers being inspected.
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(
            lambda proxy: validate_live_proxy(
                owner, proxy, repository,
                (commands.get(proxy["name"], proxy["name"])
                 if commands is not None else proxy["name"]),
                uid=uid, gid=gid,
                **({'snapshot': snapshots[proxy['container']]} if snapshots is not None else {})), proxies,
        ))


def validate_live_proxy(owner, proxy, repository, command, *, snapshot=None, uid=None, gid=None):
    command_name = proxy["name"] if isinstance(command, dict) else command
    if isinstance(command, dict):
        _validate_proxy_implementation(proxy, command, uid=uid, gid=gid)
    else:
        _managed_proxy_record(proxy)
    if "service-owner" in proxy:
        parameters = proxy["identity-parameters"]
        live_snapshot = snapshot
        if live_snapshot is None and hasattr(owner, "inspect_container"):
            live_snapshot = owner.inspect_container(proxy["container"])
        if isinstance(live_snapshot, dict):
            configured_user = live_snapshot.get("Config", {}).get("User")
            expected_user = f"{parameters['uid']}:{parameters['gid']}"
            if configured_user not in (None, expected_user):
                raise ConfigError("active proxy container user changed")
            network_mode = live_snapshot.get("HostConfig", {}).get("NetworkMode")
            if network_mode not in (None, parameters["network"]):
                raise ConfigError("active proxy container network changed")
            if proxy["name"] == "zulip":
                networks = live_snapshot.get("NetworkSettings", {}).get("Networks", {})
                mounts = [item for item in live_snapshot.get("Mounts", [])
                          if item.get("Destination") == "/run/secrets/zuliprc"]
                labels = live_snapshot.get("Config", {}).get("Labels", {})
                caddy = owner.inspect_container(proxy["caddy-container"])
                helper = owner.inspect_container(proxy["helper-container"])
                helper_credentials = [item for item in helper.get("Mounts", [])
                                      if item.get("Destination") == "/run/secrets/zuliprc"]
                caddy_credentials = [item for item in caddy.get("Mounts", [])
                                     if item.get("Destination") == "/run/secrets/zuliprc"]
                helper_networks = owner.container_networks(helper)
                caddy_networks = caddy.get("NetworkSettings", {}).get("Networks", {})
                caddy_sockets = [m for m in caddy.get("Mounts", []) if m.get("Destination") == "/run/profile-helper"]
                helper_sockets = [m for m in helper.get("Mounts", []) if m.get("Destination") == "/run/profile-helper"]
                expected_labels = {"dev.codex.service-owner": proxy["service-owner"],
                                   "dev.codex.credential-domain": "zulip"}
                caddy_mounts = caddy.get("Mounts", [])
                helper_mounts = helper.get("Mounts", [])
                try:
                    credential_identity = zulip_credential_identity(Path(proxy["credential-source"]))
                    caddy_identity = accepted_caddy_image(proxy["caddy-image-chain"], owner)
                    validate_configuration_mount(caddy, Path(proxy["configuration"]["path"]),
                                                 proxy["configuration"]["digest"])
                    caddy_image = owner.inspect_image(caddy_identity.runtime_reference)
                    helper_image = owner.inspect_image(proxy["helper-image"])
                    socket_volume = single_json(owner.run(
                        ["volume", "inspect", proxy["socket-volume"]], capture_output=True).stdout)
                except (ValueError, OSError, subprocess.SubprocessError) as error:
                    raise ConfigError("active Zulip pair identity changed") from error
                if (proxy["network"] not in networks or mounts or caddy_credentials or
                        not _zulip_mounts_exact(caddy, helper, socket_name=proxy["socket-volume"],
                            socket_source=socket_volume.get("Mountpoint"),
                            config_source=proxy["configuration"]["path"],
                            credential_source=proxy["credential-source"]) or
                        len(caddy_mounts) != 2 or len(helper_mounts) != 2 or
                        len(helper_credentials) != 1 or
                        helper_credentials[0].get("Source") != proxy["credential-source"] or
                        helper_credentials[0].get("RW") is not False or
                        credential_identity != proxy["credential-identity"] or helper_networks or
                        set(caddy_networks) != {proxy["network"]} or
                        len(caddy_sockets) != 1 or caddy_sockets[0].get("Name") != proxy["socket-volume"] or
                        caddy_sockets[0].get("RW") is not False or len(helper_sockets) != 1 or
                        helper_sockets[0].get("Name") != proxy["socket-volume"] or
                        helper_sockets[0].get("Source") != socket_volume.get("Mountpoint") or
                        helper_sockets[0].get("RW") is not True or
                        caddy_sockets[0].get("Source") != socket_volume.get("Mountpoint") or
                        not owner.owned_volume_matches(socket_volume, proxy["service-owner"],
                                                       "zulip", "profile-socket") or
                        not owner.container_matches_image(proxy["caddy-container"], caddy_image,
                            snapshot=caddy, labels={**expected_labels, "dev.codex.service-role": "zulip-caddy"}) or
                        not owner.container_matches_image(proxy["helper-container"], helper_image,
                            snapshot=helper, labels={**expected_labels, "dev.codex.service-role": "zulip-profile-helper"}) or
                        not _zulip_container_hardened(caddy, role="zulip-caddy",
                            uid=parameters["uid"], gid=parameters["gid"], network=proxy["network"],
                            entrypoint=None, command=["caddy", "run", "--config", "/etc/caddy/caddy.json"]) or
                        not _zulip_container_hardened(helper, role="zulip-profile-helper",
                            uid=parameters["uid"], gid=parameters["gid"], network="none",
                            entrypoint=["/trusted/bin/profile-helper"], command=["--profile", "zulip"]) or
                        labels.get("dev.codex.credential-domain") != "zulip"):
                    raise ConfigError("active Zulip pair isolation or runtime identity changed")
                ready = owner.run(["exec", proxy["caddy-container"], "wget", "-q", "-O", "/dev/null",
                                   "http://127.0.0.1:8787/ready"], check=False, capture_output=True)
                if ready.returncode:
                    raise ConfigError("active Zulip pair is not ready")
                network = single_json(owner.run(
                    ["network", "inspect", proxy["network"]], capture_output=True,
                ).stdout)
                network_labels = network.get("Labels", network.get("CNI", {}).get("nerdctlLabels", {}))
                if (network_labels.get("dev.codex.service-owner") != proxy["network-owner"] or
                        network_labels.get("dev.codex.public-policy") != proxy["network-policy"] or
                        proxy["network-policy"] != owner.public_network_policy_identity()):
                    raise ConfigError("active Zulip public-network policy changed")
        raw_volume = owner.run(["volume", "inspect", proxy["volume"]], capture_output=True).stdout
        volume_labels = single_json(raw_volume).get("Labels", {})
        expected_label = ("dev.codex.volume-owner" if "volume-owner" in proxy
                          else "dev.codex.service-owner")
        if volume_labels.get(expected_label) != proxy["service-owner"]:
            raise ConfigError("active proxy volume service owner changed")
    image = owner.inspect_image(proxy["image"])
    inspection = {'snapshot': snapshot} if snapshot is not None else {}
    if not owner.container_matches_image(proxy["container"], image, **inspection, labels={
            "dev.codex.sandbox-proxy": "true", "dev.codex.repository": repository,
            "dev.codex.command": command_name,
            **({"dev.codex.service-owner": proxy["service-owner"]}
               if "service-owner" in proxy else {})}):
        raise ConfigError("active proxy container failed command, repository identity, or native image validation")


def route_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    local = args.local[1:] if args.local[:1] == ["--"] else args.local
    if not local:
        raise ConfigError("a local entrypoint is required")
    runtime = runtime_directory(repo)
    lock_path = runtime / "session.lock"
    lock = lock_path.open("a+b")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        try:
            manifest = load_manifest(repo)
            if args.command not in manifest["commands"] and args.command != "zulip":
                raise ConfigError(f"unknown proxy command: {args.command}")
            return subprocess.run(local).returncode
        finally:
            lock.close()

    deadline = time.monotonic() + args.wait
    metadata_path = runtime / "session.json"
    metadata = None
    while time.monotonic() < deadline:
        try:
            metadata = _read_session(metadata_path)
            break
        except ConfigError as error:
            if metadata_path.exists():
                lock.close()
                raise
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(0.05)
            else:
                try:
                    manifest = load_manifest(repo)
                    if args.command not in manifest["commands"] and args.command != "zulip":
                        raise ConfigError(f"unknown proxy command: {args.command}")
                    return subprocess.run(local).returncode
                finally:
                    lock.close()
    lock.close()
    if metadata is None:
        raise ConfigError("sandbox session is starting but proxy metadata is unavailable")
    identity = repository_identity(repo)
    if metadata.get("version") != 4 or metadata.get("repository") != identity:
        raise ConfigError("sandbox session does not contain valid schema-4 authority")
    accepted = metadata.get("accepted", {})
    parameters = accepted.get("image-bound-parameters", {})
    services, _ = _accepted_schema4(metadata, expected_parameters=parameters)
    service = services.get(args.command)
    if service is None:
        raise ConfigError(f"proxy {args.command} is unavailable in the active sandbox session")
    recovery = service["recovery"]
    endpoint = service["endpoints"][0]
    expected_endpoint = dict(recovery.get("endpoint", {"container": recovery["container"],
                                                        "socket": "/run/sandbox-proxy/socket"}))
    if "forwarding" in recovery:
        expected_endpoint["forward"] = recovery["forwarding"]
    if endpoint != expected_endpoint or endpoint.get("container") != service["container"]["name"]:
        raise ConfigError("service endpoint authority differs from lifecycle state")
    owner = state_runtime(session_state(metadata))
    snapshot = owner.inspect_container(service["container"]["name"])
    if snapshot.get("State", {}).get("Running") is not True:
        raise ConfigError(f"proxy {args.command} is unavailable in the active sandbox session")
    command = accepted.get("policy", {}).get("commands", {}).get(args.command)
    if not isinstance(command, dict):
        raise ConfigError("service endpoint lacks accepted implementation authority")
    validate_live_proxy(owner, recovery, identity, command, snapshot=snapshot,
                        uid=parameters.get("uid"), gid=parameters.get("gid"))
    return owner.forward_proxy(service["container"]["name"])


def finalize_main(args: argparse.Namespace) -> int:
    publish_main(args)
    return agent_args_main(args)


def agent_args_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    container_repo = container_repository(args.container_repo)
    manifest = load_manifest_file(Path(args.manifest))
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    volumes = {
        proxy["name"]: proxy["volume"]
        for proxy in state.get("proxies", [])
    }
    output = Path(args.output)
    lines = [
        "--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxies",
        "--env", f"JJ_PROXY_REPO={container_repo}",
    ]
    if os.environ.get("JJ_PROXY_INSPECT"):
        lines += ["--env", "JJ_PROXY_INSPECT=1"]
    # The launcher owns the agent's /src mount through source_mounts().
    sandbox = optional_sandbox_directory(repo)
    if sandbox is not None:
        lines += ["--mount", f"type=bind,src={sandbox},dst={container_repo / '.agents/sandbox'},readonly"]
    for name, command in manifest["commands"].items():
        if name not in volumes:
            raise ConfigError(f"shared proxy state is missing command: {name}")
        lines += ["--mount", f"type=volume,src={volumes[name]},dst=/run/sandbox-proxies/{name},readonly"]
        for mount in command["mounts"]:
            if mount.get("builtin") == "git":
                # The launcher's protected .git overlay already owns this agent view.
                continue
            mode = mount["agent"]
            if mode is None:
                continue
            if any(mount["target"] == path or mount["target"].startswith(path + "/") for path in (".git", ".jj")):
                continue
            target = container_repo / mount["target"]
            if mode == "hidden":
                lines += ["--tmpfs", f"{target}:ro,noexec,nosuid,nodev,size=4k"]
            else:
                suffix = ",readonly" if mode == "read-only" else ""
                lines += ["--mount", f"type=bind,src={repo / mount['source']},dst={target}{suffix}"]
    if any("\n" in line for line in lines):
        raise ConfigError("generated container argument contains a newline")
    # The POSIX launcher prepends each argument to its existing argument list.
    output.write_text("".join(line + "\n" for line in reversed(lines)), encoding="utf-8")
    return 0


def inspect_main(args: argparse.Namespace) -> int:
    json.dump(load_manifest(Path(args.repo)), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def snapshot_main(args: argparse.Namespace) -> int:
    manifest = load_optional_manifest(Path(args.repo))
    # Apply defaults only to new repository policy, never to accepted sessions.
    manifest["capabilities"] = {**CAPABILITY_DEFAULTS, **manifest.get("capabilities", {})}
    # Snapshots are launcher-owned normalized policy. Version 1 command image
    # bindings keep installed helpers distinct from repository declarations.
    manifest["version"] = 1
    manifest = serializable_manifest(manifest)
    if "zulip" in manifest["commands"]:
        raise ConfigError("repository manifest may not override trusted command: zulip")
    if args.jj_image_command:
        builder = Path(args.jj_image_command)
        if not builder.is_absolute():
            raise ConfigError("trusted jj image command must be absolute")
        _regular_unlinked(builder, "trusted jj image command")
        if not os.access(builder, os.X_OK):
            raise ConfigError(f"trusted jj image command is not executable: {builder}")
        if "jj" in manifest["commands"]:
            raise ConfigError("repository manifest may not override trusted command: jj")
        manifest["commands"]["jj"] = {
            "image-command": [str(builder)],
            "argv": ["jj-proxy", "serve"],
            "workdir": ".",
            "network": True,
            "mounts": [{"source": ".", "target": ".", "proxy": "read-write"}],
        }
    zulip_image_command = getattr(args, "zulip_image_command", None)
    zuliprc = getattr(args, "zuliprc", None)
    if bool(zulip_image_command) != bool(zuliprc):
        raise ConfigError("trusted Zulip proxy requires both image command and credentials")
    if zulip_image_command and manifest["capabilities"]["zulip"]:
        builder = Path(zulip_image_command)
        if not builder.is_absolute():
            raise ConfigError("trusted Zulip image command must be absolute")
        _regular_unlinked(builder, "trusted Zulip image command")
        if not os.access(builder, os.X_OK):
            raise ConfigError(f"trusted Zulip image command is not executable: {builder}")
        zuliprc_mount_args(Path(zuliprc))
        manifest["commands"]["zulip"] = {
            "image-command": [str(builder)],
            "argv": ["zulip-proxy"],
            "workdir": ".",
            "network": True,
            "mounts": [],
        }
    write_atomic(Path(args.output), json.dumps(manifest, sort_keys=True))
    return 0


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--repo", required=True)
    inspect.set_defaults(function=inspect_main)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--repo", required=True)
    snapshot.add_argument("--output", required=True)
    snapshot.add_argument("--jj-image-command")
    snapshot.add_argument("--zulip-image-command")
    snapshot.add_argument("--zuliprc")
    snapshot.set_defaults(function=snapshot_main)
    join = sub.add_parser("join")
    join.add_argument("--repo", required=True)
    join.add_argument("--container-repo", required=True)
    join.add_argument("--state", required=True)
    join.add_argument("--manifest", required=True)
    join.add_argument("--images", required=True)
    join.add_argument("--accepted", required=True)
    join.add_argument("--uid", type=int, required=True)
    join.add_argument("--gid", type=int, required=True)
    join.set_defaults(function=join_main)
    attach = sub.add_parser("attach")
    attach.add_argument("--repo", required=True)
    attach.add_argument("--container-repo", required=True)
    attach.add_argument("--shared", action="store_true")
    attach.add_argument("--prefix", required=True)
    attach.add_argument("--state", required=True)
    attach.add_argument("--helper-image")
    attach.add_argument("--auth-enabled", action="store_true")
    attach.add_argument("--network", required=True)
    attach.add_argument("--manifest", required=True)
    attach.add_argument('--images')
    attach.add_argument("--agent-image")
    attach.add_argument("--uid", type=int)
    attach.add_argument("--gid", type=int)
    attach.add_argument("--source-present", action="store_true")
    attach.add_argument("--zuliprc")
    attach.set_defaults(function=attach_main)
    reset = sub.add_parser("reset")
    reset.add_argument("--repo", required=True)
    reset.set_defaults(function=reset_main)

    publish = sub.add_parser("publish")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--container-repo", required=True)
    publish.add_argument("--state", required=True)
    publish.add_argument("--manifest", required=True)
    publish.set_defaults(function=publish_main)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--repo", required=True)
    finalize.add_argument("--container-repo", required=True)
    finalize.add_argument("--state", required=True)
    finalize.add_argument("--output", required=True)
    finalize.add_argument("--manifest", required=True)
    finalize.set_defaults(function=finalize_main)
    agent = sub.add_parser("agent-args")
    agent.add_argument("--repo", required=True)
    agent.add_argument("--container-repo", required=True)
    agent.add_argument("--state", required=True)
    agent.add_argument("--output", required=True)
    agent.add_argument("--manifest", required=True)
    agent.set_defaults(function=agent_args_main)
    start = sub.add_parser("start")
    start.add_argument("--repo", required=True)
    start.add_argument("--container-repo", required=True)
    start.add_argument("--prefix", required=True)
    start.add_argument("--state", required=True)
    start.add_argument("--helper-image")
    start.add_argument("--network", required=True)
    start.add_argument("--manifest", required=True)
    start.add_argument('--images')
    start.add_argument("--agent-image")
    start.add_argument("--uid", type=int)
    start.add_argument("--gid", type=int)
    start.add_argument("--source-present", action="store_true")
    start.add_argument("--zuliprc")
    start.set_defaults(function=start_main)
    stop = sub.add_parser("stop")
    stop.add_argument("--state", required=True)
    stop.set_defaults(function=stop_main)
    route = sub.add_parser("route")
    route.add_argument("--repo", required=True)
    route.add_argument("--command", required=True)
    route.add_argument("--wait", type=float, default=10.0)
    route.add_argument("local", nargs=argparse.REMAINDER)
    route.set_defaults(function=route_main)
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None, *, runtime=None) -> int:
    global OUTER_RUNTIME
    try:
        args = parse_args(arguments)
        if runtime is not None:
            OUTER_RUNTIME = runtime
        elif args.action in {"attach", "join", "start", "publish", "finalize"}:
            OUTER_RUNTIME = image_runtime()
        return args.function(args)
    except (ConfigError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"sandbox proxies: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
