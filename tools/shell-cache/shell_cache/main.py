"""Generate, validate, and atomically replace Fish source caches."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


STALE_CACHE = 75


def parse_arguments(arguments: list[str]) -> tuple[Path, list[Path], list[str]] | None:
    destination: Path | None = None
    dependencies: list[Path] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            command = arguments[index + 1 :]
            if destination is None or not command:
                return None
            return destination, dependencies, command
        if argument not in ("--destination", "--dependency") or index + 1 >= len(arguments):
            return None
        value = Path(arguments[index + 1]).expanduser()
        if argument == "--destination":
            if destination is not None:
                return None
            destination = value
        else:
            dependencies.append(value)
        index += 2
    return None


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def valid(path: Path, fish: str, *, quiet: bool) -> bool:
    if not path.is_file():
        return False
    try:
        result = subprocess.run(
            [fish, "-n", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL if quiet else None,
        )
    except OSError:
        return False
    return result.returncode == 0


def fresh(destination: Path, dependencies: list[Path]) -> bool:
    try:
        cache_time = destination.stat().st_mtime_ns
        return all(dependency.stat().st_mtime_ns <= cache_time for dependency in dependencies)
    except OSError:
        return False


def fallback(old_valid: bool, message: str, status: int = 1) -> int:
    if old_valid:
        print(f"{message}; using previous valid cache", file=sys.stderr)
        return STALE_CACHE
    print(message, file=sys.stderr)
    return status


def clean_abandoned(destination: Path) -> None:
    prefix = f".{destination.name}."
    for candidate in destination.parent.iterdir():
        if candidate.name.startswith(prefix) and candidate.name.endswith(".pending"):
            try:
                candidate.unlink()
            except OSError:
                pass


def refresh(destination: Path, dependencies: list[Path], command: list[str], fish: str) -> int:
    old_valid = valid(destination, fish, quiet=True)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock = open(destination.parent / f".{destination.name}.lock", "a+b")
    except OSError as error:
        return fallback(old_valid, f"could not prepare cache directory: {error}")

    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError as error:
            return fallback(old_valid, f"could not lock cache: {error}")

        old_valid = valid(destination, fish, quiet=True)
        if old_valid and fresh(destination, dependencies):
            return 0
        descriptor = -1
        pending: Path | None = None
        try:
            clean_abandoned(destination)
            descriptor, name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".pending", dir=destination.parent
            )
            pending = Path(name)
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                result = subprocess.run(command, check=False, stdout=output)
                output.flush()
                os.fsync(output.fileno())
            if result.returncode:
                status = exit_status(result.returncode)
                return fallback(old_valid, f"cache producer failed with status {status}", status)
            if not valid(pending, fish, quiet=False):
                return fallback(old_valid, "cache producer generated invalid Fish syntax")
            try:
                os.replace(pending, destination)
                pending = None
                directory = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError as error:
                if pending is None:
                    print(f"cache replaced but directory sync failed: {error}", file=sys.stderr)
                    return 1
                return fallback(old_valid, f"could not replace cache: {error}")
            return 0
        except OSError as error:
            return fallback(old_valid, f"could not generate cache: {error}")
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if pending is not None:
                try:
                    pending.unlink()
                except OSError:
                    pass


def main(arguments: list[str]) -> int:
    parsed = parse_arguments(arguments)
    if parsed is None:
        print(
            "usage: refresh-fish-cache --destination path [--dependency path ...] -- command ...",
            file=sys.stderr,
        )
        return 2
    fish = shutil.which("fish")
    if fish is None:
        print("fish not found", file=sys.stderr)
        return 127
    destination, dependencies, command = parsed
    return refresh(destination, dependencies, command, fish)
