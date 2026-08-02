"""Render the historical standalone Jujutsu prompt fragment."""

from __future__ import annotations

import os
import subprocess
import sys

from .jujutsu import parse_log
from .jujutsu import QUERY
from .main import terminal_text


def marker(code: str, environment: dict[str, str]) -> str:
    if environment.get("ZSH_VERSION"):
        return f"%{{{code}%}}"
    if environment.get("FISH_VERSION"):
        # Preserve the historical fish command's charset marker protocol.
        escaped = code.replace("\x1b", r"\033")
        return f"\x1b(0{escaped}\x1b(1"
    return f"\x01{code}\x02"


def render(current_empty: bool, description: str, environment: dict[str, str]) -> str:
    red = marker("\x1b[0;31m", environment)
    faint_green = marker("\x1b[2;32m", environment)
    faint_white = marker("\x1b[2;37m", environment)
    reset = marker("\x1b[0;0m", environment)
    color = faint_green if current_empty else red
    return f" {faint_white}({color}jj{faint_white}: {reset}{description}{faint_white})"


def main(arguments: list[str]) -> int:
    if arguments:
        print("usage: jj-info", file=sys.stderr)
        return 2
    try:
        result = subprocess.run(QUERY, check=False, stdout=subprocess.PIPE)
    except OSError as error:
        print(f"jj-info: could not execute jj: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126
    if result.returncode:
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    parsed = parse_log(result.stdout)
    if parsed is None:
        print("jj-info: malformed jj log output", file=sys.stderr)
        return 1
    sys.stdout.write(render(parsed[0], terminal_text(parsed[1]), dict(os.environ)))
    return 0
