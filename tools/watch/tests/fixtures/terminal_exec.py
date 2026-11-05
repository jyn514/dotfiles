#!/usr/bin/env python3
"""Enter a fresh terminal session before replacing this helper with its command."""

import fcntl
import os
import sys
import termios


terminal, *command = sys.argv[1:]
os.setsid()
slave = os.open(terminal, os.O_RDWR)
fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
for descriptor in (0, 1, 2):
    os.dup2(slave, descriptor)
if slave > 2:
    os.close(slave)
os.execvpe(command[0], command, os.environ)
