"""Launcher-owned proxy publication and session lifetime locks."""

import fcntl
from pathlib import Path


class SessionLock:
    """Acquire on the signal-owning thread so a contended launch can be cancelled."""

    def __init__(self, directory: Path):
        self.coordination = None
        self.session = None
        try:
            self.coordination = (directory / 'coordination.lock').open('a+b')
            self.session = (directory / 'session.lock').open('a+b')
            fcntl.flock(self.coordination, fcntl.LOCK_EX)
            try:
                fcntl.flock(self.session, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.shared = True
            else:
                self.shared = False
            fcntl.flock(self.session, fcntl.LOCK_SH)
            # Published joiners only read state; they need lifetime exclusion
            # from reset, not serialization with other joiners' validation.
            if self.shared:
                self.release_coordination()
        except BaseException:
            self.close()
            raise

    def release_coordination(self):
        if self.coordination is not None:
            self.coordination.close()
            self.coordination = None

    def close(self):
        # On failed first publication, release lifetime before coordination so
        # the next launcher can become the publisher rather than a stale joiner.
        if self.session is not None:
            self.session.close()
            self.session = None
        self.release_coordination()
