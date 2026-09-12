"""Bound project image resolvers and their machine protocol."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Any


STDOUT_LIMIT = 1024 * 1024
STDERR_LIMIT = 8 * 1024 * 1024
TIMEOUT = 1800
KILL_TIMEOUT = 5


class ResolverError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedImages:
    base: str | None
    auth: str | None
    proxies: dict[str, str]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResolverError(f"resolver returned duplicate JSON field: {key}")
        result[key] = value
    return result


def _stop(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    deadline = time.monotonic() + KILL_TIMEOUT
    try:
        process.wait(timeout=KILL_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        return
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run(command: list[str], repo: Path, request: bytes, environment: dict[str, str]) -> tuple[int, bytes, bytes]:
    process = subprocess.Popen(
        command, cwd=repo, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    outputs = {process.stdout: bytearray(), process.stderr: bytearray()}
    limits = {process.stdout: STDOUT_LIMIT, process.stderr: STDERR_LIMIT}
    deadline = time.monotonic() + TIMEOUT
    try:
        process.stdin.write(request)
        process.stdin.close()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, TIMEOUT)
                for key, _ in selector.select(min(remaining, 0.1)):
                    stream = key.fileobj
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    outputs[stream].extend(chunk)
                    if len(outputs[stream]) > limits[stream]:
                        channel = "stdout" if stream is process.stdout else "stderr"
                        raise ResolverError(f"resolver {channel} exceeds {limits[stream]} bytes")
        return process.wait(), bytes(outputs[process.stdout]), bytes(outputs[process.stderr])
    except BaseException:
        _stop(process)
        raise
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def resolve_command(
    runtime: Any, repo: Path, argv: list[str], names: set[str], *, operation: str = "resolve",
) -> dict[str, Any]:
    if operation not in {"resolve", "refresh", "clean"}:
        raise ValueError(f"unsupported resolver operation: {operation}")
    requested = sorted(names)
    if not requested:
        return {}
    request = {
        "version": 1,
        "operation": operation,
        "engine": {"provider": runtime.provider, "platform": runtime.build_platform()},
        "images": requested,
    }
    encoded = (json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n").encode()
    status, stdout, stderr = _run(argv, repo, encoded, runtime.builder_environment())
    diagnostic = stderr.decode("utf-8", errors="replace").strip()
    if status:
        suffix = f": {diagnostic}" if diagnostic else ""
        raise ResolverError(f"resolver exited with status {status}{suffix}")
    try:
        result = json.loads(stdout, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ResolverError(f"resolver returned invalid JSON: {error}") from error
    if not isinstance(result, dict) or set(result) != {"version", "images"} or result["version"] != 1:
        raise ResolverError("resolver returned an unsupported result object")
    images = result["images"]
    if not isinstance(images, dict) or set(images) != names or not all(isinstance(value, str) for value in images.values()):
        raise ResolverError("resolver image names do not exactly match the request")
    # Validate the complete result before inspecting any image or permitting consumers.
    return {
        name: runtime.verify_builder_image(images[name])
        for name in requested
    }


def resolve_policy(runtime, repo, image_policy, requested, *, operation='resolve'):
    resolver = image_policy['resolver']
    if resolver['kind'] == 'command':
        return resolve_command(runtime, repo, resolver['argv'], set(requested), operation=operation)
    if runtime.provider != 'lima-docker':
        raise ResolverError('the bundled Bake resolver requires Lima-Docker')
    return {
        name: runtime.verify_builder_image(image)
        for name, image in runtime.bake(
            repo, requested, file=resolver['file'], operation=operation,
        ).items()
    }


def prepare_launch_images(
    runtime: Any, repo: Path, commands: dict[str, dict[str, Any]], *,
    include_base: bool = False, auth_builder=None, image_policy=None,
) -> PreparedImages:
    """Resolve selected project images and installed helpers through their owners."""
    repo = Path(repo)
    bindings = {name: command.get("image-target") for name, command in commands.items()}
    legacy_targets = (
        ["base"] if include_base and image_policy is None and
        (repo / ".agents/sandbox/bake").is_file() else []
    )
    builders = {"auth": auth_builder} if auth_builder is not None else {}
    for name, command in commands.items():
        if command.get("image-target"):
            if image_policy is None:
                legacy_targets.append(command["image-target"])
        elif command.get("image-command"):
            builders["proxy:" + name] = (command["image-command"], repo)
        else:
            raise ResolverError(f"proxy {name} has no bound image owner")
    from bake import resolve
    import owned_images
    owned = {
        name: owned_images.target(command) for name, (command, _) in builders.items()
        if owned_images.target(command) is not None
    }
    builders = {name: builder for name, builder in builders.items() if name not in owned}
    helper_workers = ThreadPoolExecutor(max_workers=1) if image_policy is not None and owned else None
    helper_future = helper_workers.submit(
        resolve, runtime, owned_images.ROOT, list(owned.values()),
        declaration=owned_images.declaration(owned.values()),
        captures=owned_images.source_paths(owned.values()),
    ) if helper_workers is not None else None
    project: dict[str, Any] = {}
    try:
        if image_policy is not None:
            requested = {target for target in bindings.values() if target is not None}
            if include_base:
                requested.add(image_policy["base"])
            project = resolve_policy(runtime, repo, image_policy, requested)
    except BaseException:
        if helper_workers is not None:
            helper_workers.shutdown(wait=True, cancel_futures=True)
        raise
    if (image_policy is None and include_base and
            (repo / ".agents/sandbox/base-image").is_file() and not legacy_targets):
        raise ResolverError(
            "Lima-Docker requires .agents/sandbox/bake instead of executable base-image builds"
        )
    legacy = runtime.bake(repo, legacy_targets)
    if helper_future is not None:
        try:
            helpers = helper_future.result()
        finally:
            helper_workers.shutdown(wait=True)
    else:
        helpers = resolve(
            runtime, owned_images.ROOT, list(owned.values()),
            declaration=owned_images.declaration(owned.values()),
            captures=owned_images.source_paths(owned.values()),
        ) if owned else {}
    built = runtime.run_builders(builders)

    def inspect_builder(item):
        name, result = item
        output = result.stdout.removesuffix("\n")
        if len(output) == 64 and all(character in "0123456789abcdef" for character in output):
            output = "sha256:" + output
        if result.returncode or "\n" in output:
            raise ResolverError(f"image-command for {name} did not print one immutable image hash")
        return name, runtime.verify_builder_image(output).reference

    with ThreadPoolExecutor(max_workers=max(1, min(4, len(built)))) as workers:
        inspected = dict(workers.map(inspect_builder, built.items()))
    inspected.update({name: helpers[target] for name, target in owned.items()})
    proxies = {
        name: (project[command["image-target"]].reference if image_policy is not None
               else legacy[command["image-target"]]) if command.get("image-target")
        else inspected["proxy:" + name]
        for name, command in commands.items()
    }
    base = (
        project[image_policy["base"]].reference if include_base and image_policy is not None
        else legacy.get("base", "node:24-alpine3.22") if include_base else None
    )
    return PreparedImages(base, inspected.get("auth"), proxies)
