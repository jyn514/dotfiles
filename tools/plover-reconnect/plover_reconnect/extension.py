"""Plover extension which schedules a machine reset for a selected USB model."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from .config import config_path, read

try:
    from usbx import usb
except ImportError:  # Allows package inspection and unit tests without usbx.
    usb = None  # type: ignore[assignment]


log = logging.getLogger(__name__)


class Extension:
    """The callback does no Plover work; the delayed timer does."""

    delay = 1.0
    timer_factory: Callable[..., threading.Timer] = threading.Timer

    def __init__(self, engine: Any):
        self.engine = engine
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self._generation = 0
        self._started = False

    def start(self) -> None:
        if usb is None:
            raise RuntimeError("usbx is not installed")
        with self._lock:
            if self._started:
                return
            self._generation += 1
            generation = self._generation
            try:
                usb.on_connected(self._connected)
                usb.get_devices()
            except BaseException:
                try:
                    usb.on_connected(None)
                except BaseException:
                    log.warning("unable to unregister failed USB reconnect watcher", exc_info=True)
                raise
            self._started = True
            log.debug("USB reconnect watcher started (generation %d)", generation)

    def stop(self) -> None:
        with self._lock:
            self._started = False
            self._generation += 1
            timer, self._timer = self._timer, None
            if timer is not None:
                try:
                    timer.cancel()
                except BaseException:
                    log.warning("unable to cancel USB reconnect timer", exc_info=True)
            if usb is not None:
                try:
                    usb.on_connected(None)
                except BaseException:
                    log.warning("unable to unregister USB reconnect watcher", exc_info=True)

    def _connected(self, device: Any) -> None:
        try:
            fingerprint = read(config_path())
        except (OSError, ValueError, TypeError, UnicodeError) as error:
            log.warning("USB reconnect configuration unavailable: %s", error)
            return
        if not fingerprint.matches(device):
            return
        with self._lock:
            if not self._started:
                return
            generation = self._generation
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except BaseException:
                    log.warning("unable to replace USB reconnect timer", exc_info=True)
            timer = self.timer_factory(self.delay, self._reset, args=(generation,))
            timer.daemon = True
            self._timer = timer
            timer.start()

    def _reset(self, generation: int) -> None:
        with self._lock:
            if not self._started or generation != self._generation:
                return
            self._timer = None
            self.engine.reset_machine()
