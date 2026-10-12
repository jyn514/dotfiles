"""Supply missing tmux default colors before an interactive shell starts."""

import copy
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import termios
import time

from attachment import native_tmux


# tmux answers these requests itself, with four hex digits per component.
REPLY = re.compile(rb"\x1b\](10|11);rgb:[0-9a-fA-F]{4}/[0-9a-fA-F]{4}/[0-9a-fA-F]{4}(?:\x07|\x1b\\)")


def missing_colors(fd: int, command: list[str], pane: str) -> set[int]:
    previous = termios.tcgetattr(fd)
    settings = copy.deepcopy(previous)
    settings[3] &= ~(termios.ICANON | termios.ECHO)
    settings[6][termios.VMIN] = 1
    settings[6][termios.VTIME] = 0
    received = bytearray()
    found: set[int] = set()
    try:
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        os.write(fd, b"\x1b]10;?\x07\x1b]11;?\x07")
        deadline = time.monotonic() + 0.25
        while len(found) < 2 and len(received) < 4096:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                break
            data = os.read(fd, 256)
            if not data:
                break
            received.extend(data)
            found = {int(match[1]) for match in REPLY.finditer(received)}
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, previous)
        # Keep typeahead and unrelated terminal input; only remove color replies.
        pending = REPLY.sub(b"", received)
        for start in range(0, len(pending), 256):
            subprocess.run(
                [*command, "send-keys", "-H", "-t", pane,
                 *[f"{byte:02x}" for byte in pending[start:start + 256]]],
                check=True, timeout=2,
            )
    return {10, 11} - found


def main() -> None:
    pane = os.environ.get("TMUX_PANE")
    if not os.environ.get("TMUX") or not pane or not os.isatty(0):
        return
    command = [native_tmux()]
    with open("/dev/tty", "r+b", buffering=0) as terminal:
        missing = missing_colors(terminal.fileno(), command, pane)
    if not missing:
        return
    # Read the maintained theme instead of duplicating its fallback colors.
    theme = Path(__file__).resolve().parents[2] / "config/kitty/campbell.conf"
    colors = {}
    for line in theme.read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in ("foreground", "background"):
            colors[fields[0]] = fields[1]
    style = ",".join(
        f"{attribute}={colors[key]}"
        for slot, attribute, key in ((10, "fg", "foreground"), (11, "bg", "background"))
        if slot in missing
    )
    for option in ("window-style", "window-active-style"):
        subprocess.run([*command, "set-option", "-ap", "-t", pane, option, "," + style],
                       check=True, timeout=2)


if __name__ == "__main__":
    def interrupted(signum, _frame):
        # Python unwinds the probe's finally block before exiting.
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, RuntimeError, termios.error, subprocess.SubprocessError) as error:
        print(f"tmux default colors: {error}", file=sys.stderr)
        sys.exit(1)
