"""List the installed files belonging to system packages."""

from __future__ import annotations

import shutil
import subprocess
import sys


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def package_manager() -> tuple[str, str] | None:
    dpkg = shutil.which("dpkg")
    if dpkg is not None:
        return "dpkg", dpkg
    rpm = shutil.which("rpm")
    if rpm is not None:
        return "rpm", rpm
    return None


def manager_command(packages: list[str]) -> list[str] | None:
    manager = package_manager()
    if manager is None:
        return None
    name, executable = manager
    option = "-L" if name == "dpkg" else "-ql"
    return [executable, option, "--", *packages]


def main(arguments: list[str]) -> int:
    command = manager_command(arguments)
    if command is None:
        print("no supported package manager found", file=sys.stderr)
        return 1
    try:
        result = subprocess.run(command, check=False)
    except OSError as error:
        print(f"could not run package manager: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
