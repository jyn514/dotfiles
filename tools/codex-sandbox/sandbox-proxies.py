#!/usr/bin/env python3
"""Generic sandbox proxy manifest, lifecycle, and host coordination helpers."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any


class ConfigError(Exception):
    pass


NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BARE_IMAGE_RE = re.compile(r"^[0-9a-f]{64}$")
MODES = {"read-only", "read-write", "hidden"}
CONTAINER_REPO = Path("/src/work")
COMMAND_FIELDS = {"image-command", "argv", "workdir", "network", "mounts"}
MOUNT_FIELDS = {"source", "target", "proxy", "agent"}


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
    for root, directories, files in os.walk(sandbox, followlinks=False):
        for entry in [*directories, *files]:
            candidate = Path(root) / entry
            stat = candidate.lstat()
            if candidate.is_symlink():
                raise ConfigError(f"protected sandbox configuration contains a symlink: {candidate}")
            if candidate.is_file() and stat.st_nlink != 1:
                raise ConfigError(f"protected sandbox configuration contains a hard link: {candidate}")
    repository_identity(repo)
    return repo


def load_manifest(repo: Path) -> dict[str, Any]:
    repo = validate_repository(repo)
    path = repo / ".agents" / "sandbox" / "proxy-commands.json"
    return load_manifest_file(path)


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
        return {"version": 1, "commands": {}}
    path = sandbox / "proxy-commands.json"
    if path.is_symlink():
        raise ConfigError(f"proxy manifest must not be symlinked: {path}")
    if not path.exists():
        return {"version": 1, "commands": {}}
    return load_manifest(repo)


def load_manifest_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"invalid proxy manifest: {error}") from error
    if not isinstance(data, dict) or set(data) != {"version", "commands"}:
        raise ConfigError("proxy manifest must contain exactly version and commands")
    if data["version"] != 1 or not isinstance(data["commands"], dict):
        raise ConfigError("proxy manifest must use version 1 and an object of commands")
    commands: dict[str, Any] = {}
    targets: set[str] = set()
    for name, raw in data["commands"].items():
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise ConfigError(f"invalid proxy command name: {name!r}")
        if not isinstance(raw, dict) or set(raw) != COMMAND_FIELDS:
            raise ConfigError(f"command {name} has missing or unknown fields")
        image_command = _string_array(raw["image-command"], f"command {name} image-command")
        argv = _string_array(raw["argv"], f"command {name} argv")
        if not image_command or not argv or argv[0].startswith("/"):
            raise ConfigError(f"command {name} requires non-empty commands with a PATH-resolved argv")
        workdir = _plain_relative(raw["workdir"], f"command {name} workdir", allow_dot=True)
        if not isinstance(raw["network"], bool) or not isinstance(raw["mounts"], list):
            raise ConfigError(f"command {name} has invalid network or mounts")
        mounts = []
        local_targets: set[str] = set()
        for index, mount in enumerate(raw["mounts"]):
            label = f"command {name} mount {index}"
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
        commands[name] = {**raw, "image-command": image_command, "argv": argv, "workdir": workdir, "mounts": mounts}
    return {"version": 1, "commands": commands}


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
    result = {"version": 1, "commands": {}}
    for name, command in manifest["commands"].items():
        mounts = []
        for mount in command["mounts"]:
            item = {"source": mount["source"], "target": mount["target"]}
            for mode in ("proxy", "agent"):
                if mount[mode] is not None:
                    item[mode] = mount[mode]
            mounts.append(item)
        result["commands"][name] = {**command, "mounts": mounts}
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


def git_metadata_paths(repo: Path) -> tuple[Path, Path]:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
        check=True, text=True, stdout=subprocess.PIPE,
    )
    lines = result.stdout.splitlines()
    if len(lines) != 2:
        raise ConfigError("Git returned an invalid metadata layout")
    paths = tuple(Path(line).resolve(strict=True) for line in lines)
    for path in paths:
        if any(character in str(path) for character in (",", "\n", "\r")):
            raise ConfigError("Git metadata path contains a container-mount delimiter")
        if not path.is_dir() or path.is_symlink():
            raise ConfigError(f"Git metadata directory is invalid: {path}")
    return paths


def jj_container_path(repo: Path, host_path: Path) -> Path:
    repo = repo.resolve(strict=True)
    host_path = host_path.resolve(strict=True)
    relative = Path(os.path.relpath(host_path, repo))
    target = Path(os.path.normpath(CONTAINER_REPO / relative))
    try:
        target.relative_to(CONTAINER_REPO.parent)
    except ValueError as error:
        raise ConfigError(f"Jujutsu metadata path escapes the container workspace: {host_path}") from error
    return target


def jj_proxy_metadata_mounts(repo: Path) -> list[tuple[Path, Path]]:
    repo = repo.resolve(strict=True)
    git_dir, common_dir = git_metadata_paths(repo)
    jj_repo = jj_repository_path(repo)
    candidates = sorted({git_dir, common_dir, jj_repo}, key=lambda path: len(path.parts))
    mounts: list[tuple[Path, Path]] = []
    for source in candidates:
        if any(source.is_relative_to(parent) for parent, _ in mounts):
            continue
        mounts.append((source, jj_container_path(repo, source)))
    return mounts


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
    base = Path(os.environ.get("XDG_RUNTIME_DIR", Path.home() / ".cache")) / "codex-sandbox-proxies"
    path = base / repository_identity(repo)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def lock_main(args: argparse.Namespace) -> int:
    runtime = runtime_directory(Path(args.repo))
    coordination_path = runtime / "coordination.lock"
    session_path = runtime / "session.lock"
    with coordination_path.open("a+b") as coordination, session_path.open("a+b") as session:
        while True:
            try:
                fcntl.flock(coordination, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if os.getppid() != args.parent_pid:
                    return 0
                time.sleep(0.1)
        try:
            fcntl.flock(session, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            shared = True
            fcntl.flock(session, fcntl.LOCK_SH)
        else:
            shared = False
            fcntl.flock(session, fcntl.LOCK_SH)
        Path(args.ready).write_text("shared\n" if shared else "new\n", encoding="utf-8")
        while not Path(args.coordinated).exists() and os.getppid() == args.parent_pid:
            time.sleep(0.1)
        fcntl.flock(coordination, fcntl.LOCK_UN)
        while not Path(args.release).exists() and os.getppid() == args.parent_pid:
            time.sleep(0.1)
        fcntl.flock(session, fcntl.LOCK_UN)
    return 0


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
        metadata_path.unlink(missing_ok=True)
        if isinstance(metadata, dict) and isinstance(metadata.get("state"), dict):
            stop_state(metadata["state"])
    return 0


def publish_main(args: argparse.Namespace) -> int:
    runtime = runtime_directory(Path(args.repo))
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    manifest = load_manifest_file(Path(args.manifest))
    payload = {
        "version": 1,
        "repository": repository_identity(Path(args.repo)),
        "commands": {},
        "state": state,
        "manifest": serializable_manifest(manifest),
    }
    for proxy in state.get("proxies", []):
        payload["commands"][proxy["name"]] = {"container": proxy["container"], "image": proxy["image"]}
    write_atomic(runtime / "session.json", json.dumps(payload, sort_keys=True))
    return 0


def containers_running(containers: list[str]) -> bool:
    if not containers:
        return True
    inspection = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", *containers],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return inspection.returncode == 0 and inspection.stdout.splitlines() == ["true"] * len(containers)


def cached_session_state(
    args: argparse.Namespace, repo: Path, metadata: Any, manifest: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        return None
    if metadata.get("repository") != repository_identity(repo):
        return None
    state = metadata.get("state")
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
    images = resolve_images(repo, manifest)
    proxies = state["proxies"]
    expected = {
        proxy["name"]: proxy.get("image")
        for proxy in proxies
        if isinstance(proxy, dict) and isinstance(proxy.get("name"), str)
    }
    if expected != images:
        return None
    containers = [proxy.get("container") for proxy in proxies]
    if any(not isinstance(container, str) or not container for container in containers):
        return None
    if not containers_running(containers):
        return None
    return state


def attach_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    runtime = runtime_directory(repo)
    shared = Path(args.session).read_text(encoding="utf-8").strip() == "shared"
    metadata_path = runtime / "session.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = None
    current_manifest = load_manifest_file(Path(args.manifest))
    state = cached_session_state(args, repo, metadata, current_manifest)
    if state is not None:
        write_atomic(Path(args.state), json.dumps(state, sort_keys=True))
        return 0
    if shared:
        raise ConfigError("active proxy session changed or is unavailable; restart after active sandboxes exit")
    if isinstance(metadata, dict) and isinstance(metadata.get("state"), dict):
        stop_state(metadata["state"])
    metadata_path.unlink(missing_ok=True)
    start_main(args)
    return 0


def resolve_images(repo: Path, manifest: dict[str, Any]) -> dict[str, str]:
    def resolve(name: str, command: dict[str, Any]) -> tuple[str, str]:
        result = subprocess.run(command["image-command"], cwd=repo, text=True, stdout=subprocess.PIPE)
        output = result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout
        if BARE_IMAGE_RE.fullmatch(output):
            output = "sha256:" + output
        if result.returncode or not IMAGE_RE.fullmatch(output) or result.stdout.count("\n") > 1:
            raise ConfigError(f"image-command for {name} did not print exactly one immutable image hash")
        return name, output

    commands = manifest["commands"]
    with ThreadPoolExecutor(max_workers=max(1, len(commands))) as executor:
        return dict(executor.map(lambda item: resolve(*item), commands.items()))


def _docker(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], check=True, text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
    )


def proxy_logs(container: str) -> str:
    result = subprocess.run(
        ["docker", "logs", "--tail", "200", container], check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def proxy_repository_mount_args(repo: Path, name: str, command: dict[str, Any]) -> list[str]:
    repo = repo.resolve(strict=True)
    repository_mode = ",readonly"
    if any(mount["target"] == "." and mount["proxy"] == "read-write" for mount in command["mounts"]):
        repository_mode = ""
    arguments = [
        "--mount", f"type=bind,src={repo},dst={CONTAINER_REPO}{repository_mode},bind-nonrecursive=true",
    ]
    if name == "jj":
        for source, target in jj_proxy_metadata_mounts(repo):
            arguments += [
                "--mount", f"type=bind,src={source},dst={target}{repository_mode}",
            ]
    sandbox = optional_sandbox_directory(repo)
    if sandbox is not None:
        arguments += [
            "--mount", f"type=bind,src={sandbox},dst={CONTAINER_REPO / '.agents/sandbox'},readonly",
        ]
    for mount in command["mounts"]:
        source = checked_repository_path(repo, mount["source"], f"command {name} mount source")
        checked_repository_path(repo, mount["target"], f"command {name} mount target")
        target = CONTAINER_REPO / mount["target"]
        mode = mount["proxy"]
        if mount["target"] == "." or mode is None:
            continue
        if mode == "hidden":
            arguments += ["--tmpfs", f"{target}:ro,noexec,nosuid,nodev,size=4k"]
        else:
            suffix = ",readonly" if mode == "read-only" else ""
            arguments += ["--mount", f"type=bind,src={source},dst={target}{suffix}"]
    return arguments


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


def start_one_proxy(
    args: argparse.Namespace, repo: Path, identity: str, images: dict[str, str],
    state: dict[str, Any], state_lock: threading.Lock, name: str, command: dict[str, Any],
) -> dict[str, str]:
    volume = f"{args.prefix}-{name}"
    container = f"{args.prefix}-{name}"
    proxy = {"name": name, "volume": volume, "container": container, "image": images[name]}
    with state_lock:
        state["proxies"].append(proxy)
        write_atomic(Path(args.state), json.dumps(state))
    _docker(
        "volume", "create", "--uid", str(os.getuid()), "--gid", str(os.getgid()), volume,
    )
    docker_args = [
        "run", "--detach", "--name", container, "--cap-drop=ALL",
        "--label", "dev.codex.sandbox-proxy=true",
        "--label", f"dev.codex.repository={identity}",
        "--label", f"dev.codex.command={name}",
        "--security-opt=no-new-privileges", "--read-only",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--network", args.network if command["network"] else "none",
        "--pids-limit", "96", "--memory", "2304m", "--cpus", "2",
        "--ulimit", "nofile=1024:1024", "--workdir", str(CONTAINER_REPO / command["workdir"]),
        "--entrypoint", command["argv"][0],
        "--env", "SANDBOX_PROXY_SOCKET=/run/sandbox-proxy/socket",
        "--mount", f"type=volume,src={volume},dst=/run/sandbox-proxy",
    ]
    if name == "jj":
        git_dir, common_dir = git_metadata_paths(repo)
        jj_repo = jj_repository_path(repo)
        docker_args += [
            "--env", f"JJ_PROXY_REPO={CONTAINER_REPO}",
            "--env", f"JJ_PROXY_GIT_DIR={jj_container_path(repo, git_dir)}",
            "--env", f"JJ_PROXY_COMMON_DIR={jj_container_path(repo, common_dir)}",
            "--env", f"JJ_PROXY_JJ_REPO={jj_container_path(repo, jj_repo)}",
        ]
    if name == "zulip":
        if not args.zuliprc:
            raise ConfigError("trusted Zulip proxy requires a credential path")
        docker_args += zuliprc_mount_args(Path(args.zuliprc))
    checked_repository_path(repo, command["workdir"], f"command {name} workdir")
    docker_args += proxy_repository_mount_args(repo, name, command)
    docker_args += [images[name], *command["argv"][1:]]
    _docker(*docker_args)
    deadline = time.monotonic() + 10
    readiness_error = ""
    while time.monotonic() < deadline:
        check = subprocess.run(
            ["docker", "exec", "--interactive", container, "/trusted/bin/sandbox-proxy-forward"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True,
        )
        readiness_error = check.stderr.strip()
        if check.returncode == 0:
            return proxy
        status = _docker("inspect", "--format", "{{.State.Running}}", container, capture=True).stdout.strip()
        if status != "true":
            logs = proxy_logs(container)
            detail = f":\n{logs}" if logs else ""
            raise ConfigError(f"proxy {name} exited before becoming ready{detail}")
        time.sleep(0.1)
    logs = proxy_logs(container)
    diagnostics = "\n".join(dict.fromkeys(
        output for output in (logs, readiness_error) if output
    ))
    detail = f":\n{diagnostics}" if diagnostics else ""
    raise ConfigError(f"proxy {name} did not become ready{detail}")


def start_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest = load_manifest_file(Path(args.manifest))
    images = resolve_images(repo, manifest)
    state: dict[str, Any] = {"proxies": []}
    identity = repository_identity(repo)
    write_atomic(Path(args.state), json.dumps(state))
    state_lock = threading.Lock()
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(manifest["commands"]))) as executor:
            futures = [
                executor.submit(
                    start_one_proxy, args, repo, identity, images, state, state_lock, name, command,
                )
                for name, command in manifest["commands"].items()
            ]
            for future in futures:
                future.result()
        return 0
    except Exception:
        stop_state(state)
        raise


def stop_state(state: dict[str, Any]) -> None:
    started = time.monotonic()
    containers = []
    auth = state.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("container"), str):
        containers.append(auth["container"])
    proxies = list(reversed([
        *state.get("proxies", []), *state.get("retired-proxies", []),
    ]))
    containers.extend(proxy["container"] for proxy in proxies)

    def discard(arguments: list[str]) -> None:
        subprocess.run(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Podman's forced removal waits for the container stop timeout. Send SIGKILL
    # explicitly, then remove independent containers concurrently.
    with ThreadPoolExecutor(max_workers=max(1, len(containers))) as executor:
        list(executor.map(lambda container: discard(["docker", "kill", container]), containers))
    with ThreadPoolExecutor(max_workers=max(1, len(containers))) as executor:
        list(executor.map(lambda container: discard(["docker", "rm", container]), containers))
    if os.environ.get("CODEX_SANDBOX_TIMING"):
        print(f"Sandbox proxy cleanup: containers={time.monotonic() - started:.2f}s", file=sys.stderr)
    volumes_started = time.monotonic()
    volumes = set(proxy["volume"] for proxy in proxies)
    with ThreadPoolExecutor(max_workers=max(1, len(volumes))) as executor:
        list(executor.map(lambda volume: discard(["docker", "volume", "rm", volume]), volumes))
    if os.environ.get("CODEX_SANDBOX_TIMING"):
        print(f"Sandbox proxy cleanup: volumes={time.monotonic() - volumes_started:.2f}s", file=sys.stderr)


def stop_main(args: argparse.Namespace) -> int:
    path = Path(args.state)
    if path.exists():
        contents = path.read_text(encoding="utf-8")
        if contents.strip():
            stop_state(json.loads(contents))
    return 0


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
            (runtime / "session.json").unlink(missing_ok=True)
            return subprocess.run(local).returncode
        finally:
            lock.close()

    deadline = time.monotonic() + args.wait
    metadata_path = runtime / "session.json"
    metadata = None
    while time.monotonic() < deadline:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            break
        except (FileNotFoundError, json.JSONDecodeError):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(0.05)
            else:
                try:
                    manifest = load_manifest(repo)
                    if args.command not in manifest["commands"] and args.command != "zulip":
                        raise ConfigError(f"unknown proxy command: {args.command}")
                    metadata_path.unlink(missing_ok=True)
                    return subprocess.run(local).returncode
                finally:
                    lock.close()
    lock.close()
    if metadata is None:
        raise ConfigError("sandbox session is starting but proxy metadata is unavailable")
    identity = repository_identity(repo)
    if metadata.get("repository") != identity:
        raise ConfigError("sandbox session metadata names another repository")
    proxy = metadata.get("commands", {}).get(args.command)
    if not isinstance(proxy, dict) or set(proxy) != {"container", "image"}:
        if args.command == "zulip":
            return subprocess.run(local).returncode
        raise ConfigError(f"proxy {args.command} is unavailable in the active sandbox session")
    inspection = _docker(
        "inspect", "--format",
        "{{.Config.Image}} {{index .Config.Labels \"dev.codex.sandbox-proxy\"}} "
        "{{index .Config.Labels \"dev.codex.repository\"}} {{index .Config.Labels \"dev.codex.command\"}}",
        proxy["container"], capture=True,
    ).stdout.strip().split()
    if inspection != [proxy["image"], "true", identity, args.command]:
        raise ConfigError("active proxy container failed identity validation")
    return subprocess.run(
        ["docker", "exec", "--interactive", proxy["container"], "/trusted/bin/sandbox-proxy-forward"]
    ).returncode


def finalize_main(args: argparse.Namespace) -> int:
    publish_main(args)
    return agent_args_main(args)


def agent_args_main(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    manifest = load_manifest_file(Path(args.manifest))
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    volumes = {
        proxy["name"]: proxy["volume"]
        for proxy in state.get("proxies", [])
    }
    output = Path(args.output)
    lines = ["--env", "SANDBOX_PROXY_DIR=/run/sandbox-proxies"]
    sandbox = optional_sandbox_directory(repo)
    if sandbox is not None:
        lines += ["--mount", f"type=bind,src={sandbox},dst={CONTAINER_REPO / '.agents/sandbox'},readonly"]
    for name, command in manifest["commands"].items():
        if name not in volumes:
            raise ConfigError(f"shared proxy state is missing command: {name}")
        lines += ["--mount", f"type=volume,src={volumes[name]},dst=/run/sandbox-proxies/{name},readonly"]
        for mount in command["mounts"]:
            mode = mount["agent"]
            if mode is None:
                continue
            if any(mount["target"] == path or mount["target"].startswith(path + "/") for path in (".git", ".jj")):
                continue
            target = CONTAINER_REPO / mount["target"]
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
    manifest = serializable_manifest(load_optional_manifest(Path(args.repo)))
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
    if zulip_image_command:
        builder = Path(zulip_image_command)
        if not builder.is_absolute():
            raise ConfigError("trusted Zulip image command must be absolute")
        _regular_unlinked(builder, "trusted Zulip image command")
        if not os.access(builder, os.X_OK):
            raise ConfigError(f"trusted Zulip image command is not executable: {builder}")
        zuliprc_mount_args(Path(zuliprc))
        if "zulip" in manifest["commands"]:
            raise ConfigError("repository manifest may not override trusted command: zulip")
        manifest["commands"]["zulip"] = {
            "image-command": [str(builder)],
            "argv": ["zulip-proxy"],
            "workdir": ".",
            "network": True,
            "mounts": [],
        }
    write_atomic(Path(args.output), json.dumps(manifest, sort_keys=True))
    return 0


def monitor_main(args: argparse.Namespace) -> int:
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", args.agent],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            break
        time.sleep(0.05)
    else:
        raise ConfigError("agent container did not start while proxy monitor was waiting")
    containers = [("agent", args.agent)]
    auth = state.get("auth")
    if isinstance(auth, dict) and isinstance(auth.get("container"), str):
        containers.append(("auth", auth["container"]))
    containers += [
        (proxy["name"], proxy["container"]) for proxy in state.get("proxies", [])
    ]
    waits: list[tuple[str, subprocess.Popen[str]]] = []
    selector = selectors.DefaultSelector()
    try:
        for name, container in containers:
            process = subprocess.Popen(
                ["docker", "wait", container], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            assert process.stdout is not None
            waits.append((name, process))
            selector.register(process.stdout, selectors.EVENT_READ, name)
        ready = selector.select()
        names = {key.data for key, _ in ready}
        if "agent" in names:
            return 0
        name = next(iter(names))
        print(f"sandbox proxies: proxy {name} stopped; terminating sandbox", file=sys.stderr)
        subprocess.run(
            ["docker", "rm", "--force", args.agent],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return 1
    finally:
        selector.close()
        for _, process in waits:
            process.terminate()
        for _, process in waits:
            process.wait()
            if process.stdout is not None:
                process.stdout.close()


def parse_args() -> argparse.Namespace:
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
    lock = sub.add_parser("hold-lock")
    lock.add_argument("--repo", required=True)
    lock.add_argument("--ready", required=True)
    lock.add_argument("--coordinated", required=True)
    lock.add_argument("--release", required=True)
    lock.add_argument("--parent-pid", required=True, type=int)
    lock.set_defaults(function=lock_main)
    attach = sub.add_parser("attach")
    attach.add_argument("--repo", required=True)
    attach.add_argument("--session", required=True)
    attach.add_argument("--prefix", required=True)
    attach.add_argument("--state", required=True)
    attach.add_argument("--helper-image", required=True)
    attach.add_argument("--auth-enabled", action="store_true")
    attach.add_argument("--network", required=True)
    attach.add_argument("--manifest", required=True)
    attach.add_argument("--zuliprc")
    attach.set_defaults(function=attach_main)
    reset = sub.add_parser("reset")
    reset.add_argument("--repo", required=True)
    reset.set_defaults(function=reset_main)

    publish = sub.add_parser("publish")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--state", required=True)
    publish.add_argument("--manifest", required=True)
    publish.set_defaults(function=publish_main)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--repo", required=True)
    finalize.add_argument("--state", required=True)
    finalize.add_argument("--output", required=True)
    finalize.add_argument("--manifest", required=True)
    finalize.set_defaults(function=finalize_main)
    agent = sub.add_parser("agent-args")
    agent.add_argument("--repo", required=True)
    agent.add_argument("--state", required=True)
    agent.add_argument("--output", required=True)
    agent.add_argument("--manifest", required=True)
    agent.set_defaults(function=agent_args_main)
    start = sub.add_parser("start")
    start.add_argument("--repo", required=True)
    start.add_argument("--prefix", required=True)
    start.add_argument("--state", required=True)
    start.add_argument("--helper-image", required=True)
    start.add_argument("--network", required=True)
    start.add_argument("--manifest", required=True)
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
    monitor = sub.add_parser("monitor")
    monitor.add_argument("--state", required=True)
    monitor.add_argument("--agent", required=True)
    monitor.set_defaults(function=monitor_main)
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        return args.function(args)
    except (ConfigError, OSError, subprocess.SubprocessError) as error:
        print(f"sandbox proxies: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
