import importlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock


class Signal:
    def connect(self, callback):
        self.callback = callback


class ListWidget:
    def __init__(self, parent=None):
        self.items = []
        self.row = -1

    def clear(self):
        self.items.clear()

    def addItem(self, value):
        self.items.append(value)

    def currentRow(self):
        return self.row


class ButtonBox:
    class StandardButton:
        Save = 1
        Cancel = 2

    def __init__(self, buttons, parent=None):
        self.accepted = Signal()
        self.rejected = Signal()


class Label:
    def __init__(self, value):
        self.value = value


class Layout:
    def __init__(self, parent=None):
        self.widgets = []

    def addWidget(self, widget):
        self.widgets.append(widget)


class FakeTool:
    def __init__(self, engine):
        self.engine = engine

    def accept(self):
        self.accepted = True

    def reject(self):
        self.rejected = True


def load_tool_module():
    plover = types.ModuleType("plover")
    plover_gui = types.ModuleType("plover.gui_qt")
    plover_tool = types.ModuleType("plover.gui_qt.tool")
    plover_tool.Tool = FakeTool
    pyside = types.ModuleType("PySide6")
    widgets = types.ModuleType("PySide6.QtWidgets")
    widgets.QDialogButtonBox = ButtonBox
    widgets.QLabel = Label
    widgets.QListWidget = ListWidget
    widgets.QVBoxLayout = Layout
    names = ("plover", "plover.gui_qt", "plover.gui_qt.tool", "PySide6", "PySide6.QtWidgets")
    previous = {name: sys.modules.get(name) for name in names}
    sys.modules.update({
        "plover": plover,
        "plover.gui_qt": plover_gui,
        "plover.gui_qt.tool": plover_tool,
        "PySide6": pyside,
        "PySide6.QtWidgets": widgets,
    })
    try:
        return importlib.import_module("plover_reconnect.tool")
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


tool = load_tool_module()


class ToolTest(unittest.TestCase):
    def test_reload_sorts_devices_and_labels_unknown_descriptors(self):
        devices = [
            SimpleNamespace(manufacturer="Zeta", product="Board", vid=3, pid=4),
            SimpleNamespace(manufacturer=None, product=None, vid=1, pid=2),
            SimpleNamespace(manufacturer="Alpha", product="Board", vid=5, pid=6),
        ]
        widget = tool.DeviceTool.__new__(tool.DeviceTool)
        widget.list = ListWidget()
        with mock.patch.object(tool, "usb", mock.Mock(get_devices=mock.Mock(return_value=devices))):
            widget._reload()
        self.assertEqual(widget.devices, [devices[1], devices[2], devices[0]])
        self.assertEqual(widget.list.items, [
            "Unknown manufacturer — Unknown product",
            "Alpha — Board",
            "Zeta — Board",
        ])

    def test_save_writes_the_selected_device_fingerprint(self):
        device = SimpleNamespace(manufacturer="Maker", product="Model", vid=7, pid=8)
        widget = tool.DeviceTool.__new__(tool.DeviceTool)
        widget.list = ListWidget()
        widget.list.row = 0
        widget.devices = [device]
        with mock.patch.object(tool, "write") as write, mock.patch.object(
            tool, "config_path", return_value="config.json"
        ):
            widget._save()
        write.assert_called_once_with(
            "config.json", tool.DeviceFingerprint(7, 8, "Maker", "Model")
        )
        self.assertTrue(widget.accepted)


if __name__ == "__main__":
    unittest.main()
