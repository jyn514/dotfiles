"""Run a shell command repeatedly without displaying partial frames."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNNER = ROOT / "libexec/runinpty.py"


class Options(NamedTuple):
    interval: str
    shell: str
    command: str


def parse(arguments: list[str], default_shell: str) -> Options:
    interval = "2"
    shell = default_shell or "sh"
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith("-n"):
            value = argument[2:]
            if not value:
                index += 1
                if index == len(arguments):
                    raise ValueError("-n requires an interval")
                value = arguments[index]
            interval = value
        elif argument.startswith("-x"):
            value = argument[2:]
            if not value:
                index += 1
                if index == len(arguments):
                    raise ValueError("-x requires a shell")
                value = arguments[index]
            shell = value
        else:
            break
        index += 1
    command = " ".join(arguments[index:])
    if not command:
        raise ValueError("a command is required")
    return Options(interval, shell, command)


def status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def run(
    arguments: list[str], *, capture: bool = False, merge_stderr: bool = False
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            arguments,
            check=False,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if merge_stderr else None,
        )
    except OSError as error:
        print(f"watch: could not execute {arguments[0]!r}: {error}", file=sys.stderr)
        return None


def terminal(command: str, *arguments: str, ignore_failure: bool = False) -> int:
    result = run([command, *arguments])
    if result is None:
        return 0 if ignore_failure else 127
    return 0 if ignore_failure else status(result.returncode)


def main(arguments: list[str]) -> int:
    try:
        options = parse(arguments, os.environ.get("SHELL", "sh"))
    except ValueError as error:
        print(f"usage: watch [-n <interval>] [-x <shell>] <...args>: {error}", file=sys.stderr)
        return 1

    print(f"{options.interval} {options.shell} {options.command}", file=sys.stderr)
    runner = os.environ.get("WATCH_RUNNER", str(DEFAULT_RUNNER))
    terminal("tput", "smcup", ignore_failure=True)
    try:
        clear_status = terminal("clear")
        if clear_status:
            return clear_status
        while True:
            command = run(
                [runner, options.shell, "-c", options.command],
                capture=True,
                merge_stderr=True,
            )
            if command is None:
                output = b""
                command_status = 127
            else:
                output = command.stdout.rstrip(b"\n")
                command_status = status(command.returncode)

            clear_status = terminal("clear", "-x")
            if clear_status:
                return clear_status
            sys.stdout.buffer.write(output)
            if command_status:
                sys.stdout.buffer.write(f"\n[exit {command_status}]".encode())
            sys.stdout.buffer.flush()

            sleep_status = terminal("sleep", options.interval)
            if sleep_status:
                return sleep_status
    except KeyboardInterrupt:
        return 130
    finally:
        terminal("tput", "rmcup", ignore_failure=True)
