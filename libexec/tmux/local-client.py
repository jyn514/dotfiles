"""Check the source of tmux's selected client for the current pane."""

import os
import subprocess
import sys

from attachment import Tmux, client_source, native_tmux


def main() -> bool:
    pane = os.environ.get("TMUX_PANE")
    connection = os.environ.get("TMUX", "")
    if not pane or not connection:
        return False
    socket = connection.rsplit(",", 2)[0]
    pid = Tmux(native_tmux(), socket).run(
        "display-message", "-p", "-t", pane, "#{client_pid}")
    return client_source(pid) == "local"


if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        sys.exit(1)
