"""Enter an editor command for one picker selection in the current tmux pane."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from picker_actions.drag import exit_status
from picker_actions.selections import parse


def editor_command(selection: bytes) -> str | None:
    try:
        editor = shlex.split(os.environ.get("EDITOR", "vi"))
    except ValueError:
        return None
    if not editor:
        return None
    return shlex.join([*editor, os.fsdecode(selection)])


def main(arguments: list[str]) -> int:
    chosen = parse(arguments)
    if chosen is None:
        print("usage: picker-action edit [--read0 | [--] selection]", file=sys.stderr)
        return 2
    if not chosen:
        return 0
    if len(chosen) != 1:
        print("edit requires exactly one selection", file=sys.stderr)
        return 2

    command = editor_command(chosen[0])
    if command is None:
        print("EDITOR is empty or malformed", file=sys.stderr)
        return 2
    tmux = shutil.which("tmux")
    if tmux is None:
        print("tmux not found", file=sys.stderr)
        return 127
    try:
        result = subprocess.run(
            [
                tmux,
                "send-keys",
                "C-q",
                ";",
                "send-keys",
                "-l",
                command,
                ";",
                "send-keys",
                "C-m",
            ],
            check=False,
        )
    except OSError as error:
        print(f"could not send editor command to tmux: {error}", file=sys.stderr)
        return 127
    return exit_status(result.returncode)
