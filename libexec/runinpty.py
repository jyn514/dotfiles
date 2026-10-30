#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2001, 2002, 2003, 2004, 2005, 2006 Python Software Foundation; All Rights Reserved
# SPDX-FileCopyrightText: 2024 Jade Lovelace
# SPDX-License-Identifier: LGPL-2.1-or-later
"""
This script exists to lose Lix a dependency on expect(1) for the ability to run
something in a pty.

Yes, it could be replaced by script(1) but macOS and Linux script(1) have
diverged sufficiently badly that even specifying a subcommand to run is not the
same.
"""
import pty
import sys
import os
import signal
from termios import ONLCR, ONLRET, ONOCR, OPOST, TCSAFLUSH, tcgetattr, tcsetattr
from tty import setraw
import termios

def setup_terminal():
    # does not matter which fd we use because we are in a fresh pty
    modi = tcgetattr(pty.STDOUT_FILENO)
    [iflag, oflag, cflag, lflag, ispeed, ospeed, cc] = modi

    # Turning \n into \r\n is not cool, Linux!
    oflag &= ~ONLCR
    # I don't know what "implementation dependent postprocessing means" but it
    # sounds bad
    oflag &= ~OPOST
    # Assume that NL performs the role of CR; do not insert CRs at column 0
    oflag |= ONLRET | ONOCR

    modi = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]

    tcsetattr(pty.STDOUT_FILENO, TCSAFLUSH, modi)


def spawn(argv: list[str], *, watch_cancellation: bool = False):
    """
    As opposed to pty.spawn, this one more seriously controls the pty settings.
    Necessary to turn off such fun functionality as onlcr (LF to CRLF).

    This is essentially copy pasted from pty.spawn, since there is no way to
    hook the child pre-execve
    """
    pid, master_fd = pty.fork()
    if pid == pty.CHILD:
        setup_terminal()
        os.execlp(argv[0], *argv)

    try:
        mode = tcgetattr(pty.STDIN_FILENO)
        setraw(pty.STDIN_FILENO)
        if watch_cancellation:
            raw_mode = tcgetattr(pty.STDIN_FILENO)
            raw_mode[3] |= mode[3] & termios.ISIG
            tcsetattr(pty.STDIN_FILENO, TCSAFLUSH, raw_mode)
        restore = True
    except termios.error:
        restore = False

    interrupted = False

    def interrupt(signum, frame):
        nonlocal interrupted
        interrupted = True
        # Continue the existing copy loop so command cleanup can write output.
        try:
            os.killpg(pid, signal.SIGINT)
        except ProcessLookupError:
            pass

    if watch_cancellation:
        previous_handler = signal.signal(signal.SIGINT, interrupt)
    try:
        pty._copy(master_fd, pty._read, pty._read) # type: ignore
    finally:
        if restore:
            tcsetattr(pty.STDIN_FILENO, TCSAFLUSH, mode) # type: ignore
        if watch_cancellation:
            signal.signal(signal.SIGINT, previous_handler)

    os.close(master_fd)
    status = os.waitpid(pid, 0)[1]
    if interrupted:
        raise KeyboardInterrupt
    return status


def main():
    # Only newly loaded built-in watch callers opt in. Already-running callers
    # and WATCH_RUNNER overrides keep the legacy terminal/cancellation behavior.
    watch_cancellation = sys.argv[1:2] == ['--watch-cancellation']
    argv = sys.argv[2:] if watch_cancellation else sys.argv[1:]
    if not argv:
        print(f'Usage: {sys.argv[0]} [command args]', file=sys.stderr)
        sys.exit(1)

    try:
        status = spawn(argv, watch_cancellation=watch_cancellation)
    except KeyboardInterrupt:
        if not watch_cancellation:
            raise
        sys.exit(130)
    returncode = os.waitstatus_to_exitcode(status)
    # Report shell-style signal status to watch, not a negative code that
    # sys.exit would wrap into an unrelated ordinary exit status.
    sys.exit(returncode if returncode >= 0 else 128 - returncode)


if __name__ == '__main__':
    main()
