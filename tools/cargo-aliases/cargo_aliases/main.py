"""Render Cargo commands and aliases as Fish abbreviations."""

from __future__ import annotations

import subprocess
import sys


def fish_literal(value: str) -> str:
    """Quote one value for Fish without evaluation."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render(command_list: str) -> str:
    lines = command_list.splitlines()
    output: list[str] = []
    for line in lines[1:]:
        fields = line.strip().split(None, 1)
        if not fields:
            continue
        name = fields[0]
        description = fields[1].strip() if len(fields) == 2 else ""
        if description.startswith("alias: "):
            expansion = description.removeprefix("alias: ")
            output.append(
                "abbr --add --command cargo "
                f"{fish_literal(name)} -- {fish_literal(expansion)}"
            )
            command = expansion
        else:
            command = name
        if name not in ("c", "d"):
            output.append(
                f"abbr --add --global {fish_literal('c' + name)} -- "
                f"{fish_literal('cargo ' + command)}"
            )
    return "".join(line + "\n" for line in output)


def main(arguments: list[str]) -> int:
    if len(arguments) > 1:
        print("usage: generate-cargo-fish-abbr [cargo-command]", file=sys.stderr)
        return 2
    cargo = arguments[0] if arguments else "cargo"
    try:
        result = subprocess.run(
            [cargo, "--list"],
            check=False,
            stdout=subprocess.PIPE,
        )
    except OSError as error:
        print(f"could not run Cargo: {error}", file=sys.stderr)
        return 127
    if result.returncode:
        return result.returncode if result.returncode > 0 else 128 - result.returncode
    try:
        command_list = result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        print(f"Cargo command list is not UTF-8: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(render(command_list))
    return 0
