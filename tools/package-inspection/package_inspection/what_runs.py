"""Find executable files installed by system packages."""

from __future__ import annotations

import os
import subprocess
import sys

from package_inspection.what_belongs import exit_status, manager_command


def executable_paths(output: bytes) -> list[bytes]:
    paths: list[bytes] = []
    for path in output.split(b"\n"):
        if not path:
            continue
        if os.path.isfile(path) and os.access(path, os.X_OK):
            paths.append(path)
    return paths


def main(arguments: list[str]) -> int:
    command = manager_command(arguments)
    if command is None:
        print("no supported package manager found", file=sys.stderr)
        return 1
    try:
        result = subprocess.run(command, check=False, stdout=subprocess.PIPE)
    except OSError as error:
        print(f"could not run package manager: {error}", file=sys.stderr)
        return 127
    if result.returncode:
        return exit_status(result.returncode)

    paths = executable_paths(result.stdout)
    if paths:
        try:
            sys.stdout.buffer.write(b"\n".join(paths) + b"\n")
        except BrokenPipeError:
            return 1
    return 0
