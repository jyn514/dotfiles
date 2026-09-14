import importlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock


class Signal:
    def connect(self, callback):
        self.callback = callback


class Button:
    def __init__(self):
        self.clicked = Signal()
        self.enabled = True

    def setEnabled(self, enabled):
        self.enabled = enabled


class ListWidget:
    def __init__(self, parent=None):
        self.items = []
        self.row = -1
        self.currentRowChanged = Signal()

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
        self.save = Button()

    def button(self, standard_button):
        return self.save


class Label:
    def __init__(self, value):
        self.value = value


class MessageBox:
    last_call = None

    @classmethod
    def critical(cls, parent, title, message):
        cls.last_call = (parent, title, message)

    @classmethod
    def warning(cls, parent, title, message):
        cls.last_call = (parent, title, message)


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
    widgets.QMessageBox = MessageBox
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
    def test_save_button_is_explicitly_wired_and_requires_selection(self):
        device = SimpleNamespace(manufacturer="Maker", product="Model", vid=7, pid=8)
        with mock.patch.object(tool, "usb", mock.Mock(get_devices=mock.Mock(return_value=[device]))):
            widget = tool.DeviceTool(mock.Mock())
        self.assertFalse(widget.save_button.enabled)
        widget.devices = [device]
        widget.list.row = 0
        widget._selection_changed(0)
        self.assertTrue(widget.save_button.enabled)
        with mock.patch.object(tool, "write") as write, mock.patch.object(
            tool, "config_path", return_value="config.json"
        ):
            widget.save_button.clicked.callback(True)
        write.assert_called_once_with(
            "config.json", tool.DeviceFingerprint(7, 8, "Maker", "Model")
        )
        self.assertTrue(widget.accepted)

    def test_save_reports_write_errors_without_closing(self):
        device = SimpleNamespace(manufacturer="Maker", product="Model", vid=7, pid=8)
        widget = tool.DeviceTool.__new__(tool.DeviceTool)
        widget.list = ListWidget()
        widget.list.row = 0
        widget.devices = [device]
        MessageBox.last_call = None
        with mock.patch.object(
            tool, "config_path", side_effect=ImportError("missing config API")
        ):
            widget._save(True)
        self.assertFalse(hasattr(widget, "accepted"))
        self.assertEqual(MessageBox.last_call[1:], (
            "USB reconnect", "Unable to save the selected device:\nmissing config API"
        ))

    def test_reload_reports_device_enumeration_errors(self):
        widget = tool.DeviceTool.__new__(tool.DeviceTool)
        widget.list = ListWidget()
        widget.devices = []
        widget.save_button = Button()
        MessageBox.last_call = None
        with mock.patch.object(
            tool, "usb", mock.Mock(get_devices=mock.Mock(side_effect=OSError("USB unavailable")))
        ):
            widget._reload()
        self.assertEqual(MessageBox.last_call[1:], (
            "USB reconnect", "Unable to list USB devices:\nUSB unavailable"
        ))
        self.assertEqual(widget.devices, [])

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

    def test_save_warns_when_extension_is_disabled(self):
        device = SimpleNamespace(manufacturer="Maker", product="Model", vid=7, pid=8)
        widget = tool.DeviceTool.__new__(tool.DeviceTool)
        widget._engine = SimpleNamespace(config={"enabled_extensions": set()})
        widget.list = ListWidget()
        widget.list.row = 0
        widget.devices = [device]
        MessageBox.last_call = None
        with mock.patch.object(tool, "write"), mock.patch.object(
            tool, "config_path", return_value="config.json"
        ):
            widget._save()
        self.assertEqual(MessageBox.last_call[1:], (
            "USB reconnect extension is disabled",
            "The device will be saved, but automatic reconnection will not run "
            "until plover-reconnect is enabled in Configure -> Plugins.",
        ))
        self.assertTrue(widget.accepted)


if __name__ == "__main__":
    unittest.main()
