"""Show a modal break reminder and keep its window above others."""

from __future__ import annotations

import subprocess
import sys
import time


DIALOG_ARGUMENTS = [
    "zenity",
    "--question",
    "--text=please",
    "--title=take a break",
    "--ok-label=i will",
    "--cancel-label=fuck you",
    "--modal",
]


def exit_status(returncode: int) -> int:
    return returncode if returncode >= 0 else 128 - returncode


def window_for_pid(output: bytes, pid: int) -> bytes | None:
    expected = str(pid).encode()
    for line in output.splitlines():
        fields = line.split(None, 4)
        if len(fields) >= 3 and fields[2] == expected:
            return fields[0]
    return None


def raise_dialog(pid: int) -> None:
    try:
        listed = subprocess.run(
            ["wmctrl", "-l", "-p"],
            check=False,
            stdout=subprocess.PIPE,
        )
    except OSError as error:
        print(f"take-a-break: could not execute wmctrl: {error}", file=sys.stderr)
        return
    if listed.returncode:
        return
    window = window_for_pid(listed.stdout, pid)
    if window is None:
        return
    try:
        subprocess.run(
            [b"wmctrl", b"-i", b"-r", window, b"-b", b"add,above"],
            check=False,
        )
    except OSError as error:
        print(f"take-a-break: could not execute wmctrl: {error}", file=sys.stderr)


def main(arguments: list[str]) -> int:
    if arguments:
        print("usage: take-a-break", file=sys.stderr)
        return 2
    try:
        dialog = subprocess.Popen(DIALOG_ARGUMENTS)
    except OSError as error:
        print(f"take-a-break: could not execute zenity: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126

    try:
        time.sleep(0.2)
        raise_dialog(dialog.pid)
        return exit_status(dialog.wait())
    except KeyboardInterrupt:
        dialog.terminate()
        dialog.wait()
        return 130
