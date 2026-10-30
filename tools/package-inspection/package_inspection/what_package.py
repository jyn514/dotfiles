"""Find the system package owning an executable."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

from package_inspection.what_belongs import exit_status, package_manager


def ownership_command(arguments: list[str]) -> list[str] | None:
    if not arguments:
        return None
    executable = shutil.which(arguments[0])
    if executable is None:
        return None
    try:
        resolved = str(Path(executable).resolve(strict=True))
    except OSError:
        return None

    manager = package_manager()
    if manager is None:
        return []
    name, manager_executable = manager
    option = "-S" if name == "dpkg" else "-qf"
    return [manager_executable, option, "--", resolved, *arguments[1:]]


def directory_alias(canonical: str) -> Path | None:
    target = Path(canonical)
    try:
        alias = Path("/") / target.relative_to("/usr")
        # Keep target ownership: a separately packaged final symlink is not
        # a directory alias, even when it resolves to the same executable.
        if not alias.is_symlink() and alias.parent.resolve(strict=True) == target.parent:
            return alias
    except (ValueError, OSError, RuntimeError):
        pass
    return None


def query_dpkg(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    original = subprocess.run(command, check=False, capture_output=True)
    # dpkg-query documents 1 as a fully or partially missing match; 2 is fatal.
    if original.returncode != 1:
        return original
    alias = directory_alias(command[3])
    if alias is None:
        return original
    try:
        # Additional operands can fail while the canonical target is owned.
        # Ask dpkg separately rather than interpreting its output text.
        if len(command) > 4:
            target = subprocess.run(command[:4], check=False, capture_output=True)
            if target.returncode != 1:
                return original
        retry = subprocess.run(
            [*command[:3], str(alias), *command[4:]], check=False, capture_output=True
        )
    except OSError:
        return original
    return retry if retry.returncode == 0 else original


def main(arguments: list[str]) -> int:
    if not arguments:
        print("usage: what-package executable [additional-path ...]", file=sys.stderr)
        return 2
    command = ownership_command(arguments)
    if command is None:
        print(f"executable not found: {arguments[0]}", file=sys.stderr)
        return 127
    if not command:
        print("no supported package manager found", file=sys.stderr)
        return 1
    try:
        if command[1] == "-S":
            result = query_dpkg(command)
            sys.stdout.buffer.write(result.stdout)
            sys.stderr.buffer.write(result.stderr)
        else:
            result = subprocess.run(command, check=False)
    except OSError as error:
        print(f"could not run package manager: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
