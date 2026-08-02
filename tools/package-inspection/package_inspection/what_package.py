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
        result = subprocess.run(command, check=False)
    except OSError as error:
        print(f"could not run package manager: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
