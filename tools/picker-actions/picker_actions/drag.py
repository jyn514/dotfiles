"""Open one or more picker selections in Dragon."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def read_records(data: bytes) -> list[bytes] | None:
    if not data:
        return []
    if not data.endswith(b"\0"):
        return None
    records = data[:-1].split(b"\0")
    if records == [b""]:
        return []
    if any(not record for record in records):
        return None
    return records


def selections(arguments: list[str]) -> list[bytes] | None:
    if arguments == ["--read0"]:
        return read_records(sys.stdin.buffer.read())
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if not arguments:
        return None
    return [os.fsencode(argument) for argument in arguments]


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def main(arguments: list[str]) -> int:
    chosen = selections(arguments)
    if chosen is None:
        print("usage: dragon.sh [--read0 | [--] selection ...]", file=sys.stderr)
        return 2
    if not chosen:
        return 0

    executable = shutil.which("dragon")
    if executable is None:
        print("dragon not found", file=sys.stderr)
        return 127
    positional = [b"./" + value if value.startswith(b"-") else value for value in chosen]
    try:
        result = subprocess.run(
            [os.fsencode(executable), b"-x", *positional],
            check=False,
        )
    except OSError as error:
        print(f"could not run dragon: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
