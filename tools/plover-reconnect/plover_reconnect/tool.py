"""Qt configuration tool for selecting the USB model to watch."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from plover.gui_qt.tool import Tool
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QMessageBox,
    QVBoxLayout,
)

from .config import DeviceFingerprint, config_path, write


try:
    from usbx import usb
except ImportError:
    usb = None  # type: ignore[assignment]


log = logging.getLogger(__name__)


class DeviceTool(Tool):
    TITLE = "USB reconnect"
    ICON = str(Path(__file__).with_name("resources") / "usb-reconnect.svg")
    ROLE = "plover-reconnect"

    def __init__(self, engine: Any):
        super().__init__(engine)
        self.devices: list[Any] = []
        self.list = QListWidget(self)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        self.list.currentRowChanged.connect(self._selection_changed)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the USB device model that should reconnect Plover."))
        layout.addWidget(self.list)
        layout.addWidget(self.buttons)
        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        self.devices = []
        if usb is None:
            return
        try:
            self.devices = sorted(
                usb.get_devices(),
                key=lambda device: (device.manufacturer or "", device.product or ""),
            )
        except Exception as error:
            self._report_error("Unable to list USB devices", error)
            return
        for device in self.devices:
            manufacturer = device.manufacturer or "Unknown manufacturer"
            product = device.product or "Unknown product"
            self.list.addItem(f"{manufacturer} — {product}")

    def _selection_changed(self, row: int) -> None:
        self.save_button.setEnabled(row >= 0)

    def _report_error(self, message: str, error: Exception) -> None:
        log.exception("%s: %s", message, error)
        QMessageBox.critical(self, "USB reconnect", f"{message}:\n{error}")

    def _save(self, checked: bool = False) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        device = self.devices[row]
        try:
            enabled = self.ROLE in self._engine.config["enabled_extensions"]
        except (AttributeError, KeyError, TypeError):
            enabled = True
            log.warning("unable to determine whether the USB reconnect extension is enabled")
        if not enabled:
            QMessageBox.warning(
                self,
                "USB reconnect extension is disabled",
                "The device will be saved, but automatic reconnection will not "
                "run until plover-reconnect is enabled in Configure -> Plugins.",
            )
        try:
            write(config_path(), DeviceFingerprint(
                device.vid, device.pid, device.manufacturer, device.product
            ))
        except Exception as error:
            self._report_error("Unable to save the selected device", error)
            return
        self.accept()
