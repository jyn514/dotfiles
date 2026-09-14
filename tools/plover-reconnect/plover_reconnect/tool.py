"""Qt configuration tool for selecting the USB model to watch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plover.gui_qt.tool import Tool
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QListWidget, QVBoxLayout

from .config import DeviceFingerprint, config_path, write


try:
    from usbx import usb
except ImportError:
    usb = None  # type: ignore[assignment]


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
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the USB device model that should reconnect Plover."))
        layout.addWidget(self.list)
        layout.addWidget(self.buttons)
        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        if usb is None:
            return
        self.devices = sorted(
            usb.get_devices(),
            key=lambda device: (device.manufacturer or "", device.product or ""),
        )
        for device in self.devices:
            manufacturer = device.manufacturer or "Unknown manufacturer"
            product = device.product or "Unknown product"
            self.list.addItem(f"{manufacturer} — {product}")

    def _save(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        device = self.devices[row]
        write(config_path(), DeviceFingerprint(
            device.vid, device.pid, device.manufacturer, device.product
        ))
        self.accept()
