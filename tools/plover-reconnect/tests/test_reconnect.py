import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from plover_reconnect.config import DeviceFingerprint, parse, read, write
from plover_reconnect import extension


class FakeTimer:
    instances = []
    fail_cancel = False

    def __init__(self, delay, callback, args=()):
        self.callback = callback
        self.args = args
        self.cancelled = False
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        if self.__class__.fail_cancel:
            raise RuntimeError("cancel failed")
        self.cancelled = True

    def fire(self):
        self.callback(*self.args)


class Device:
    def __init__(self, vid, pid):
        self.vid, self.pid = vid, pid


class ReconnectTest(unittest.TestCase):
    def setUp(self):
        FakeTimer.instances.clear()
        FakeTimer.fail_cancel = False
        self.usb = mock.Mock()
        self.engine = mock.Mock()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "plover-reconnect.json"
        self.usb.get_devices.return_value = [Device(1, 2)]

    def tearDown(self):
        self.temp.cleanup()

    def extension(self):
        result = extension.Extension(self.engine)
        result.timer_factory = FakeTimer
        return result

    def test_start_enumeration_and_unrelated_device_do_not_reset(self):
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            watcher._connected(Device(9, 9))
        self.engine.reset_machine.assert_not_called()
        self.usb.get_devices.assert_called_once_with()

    def test_matching_events_coalesce_and_reset_after_timer(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            watcher._connected(Device(1, 2))
            first = FakeTimer.instances[-1]
            watcher._connected(Device(1, 2))
            second = FakeTimer.instances[-1]
            second.fire()
        self.assertTrue(first.cancelled)
        self.engine.reset_machine.assert_called_once_with()

    def test_stop_invalidates_pending_timer(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            watcher._connected(Device(1, 2))
            timer = FakeTimer.instances[-1]
            watcher.stop()
            timer.fire()
        self.engine.reset_machine.assert_not_called()
        self.assertEqual(self.usb.on_connected.call_args_list[-1].args, (None,))

    def test_stop_is_idempotent_and_cancellation_failure_is_logged(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ), self.assertLogs(extension.log, "WARNING"):
            watcher.start()
            watcher._connected(Device(1, 2))
            FakeTimer.fail_cancel = True
            watcher.stop()
            watcher.stop()
        self.engine.reset_machine.assert_not_called()

    def test_old_generation_cannot_reset_after_restart(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            watcher._connected(Device(1, 2))
            old_timer = FakeTimer.instances[-1]
            watcher.stop()
            watcher.start()
            old_timer.fire()
        self.engine.reset_machine.assert_not_called()

    def test_failed_start_unregisters_callback(self):
        self.usb.get_devices.side_effect = RuntimeError("monitor failed")
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb):
            with self.assertRaises(RuntimeError):
                watcher.start()
        self.assertEqual(self.usb.on_connected.call_args_list[-1].args, (None,))

    def test_malformed_configuration_does_not_reset(self):
        self.path.write_text('{"schema": 1, "device": {"vid": 1}}', encoding="utf-8")
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            watcher._connected(Device(1, 2))
        self.engine.reset_machine.assert_not_called()

    def test_configuration_round_trips_optional_labels(self):
        fingerprint = DeviceFingerprint(1, 2, "Maker", "Model")
        write(self.path, fingerprint)
        self.assertEqual(read(self.path), fingerprint)

    def test_configuration_rejects_boolean_identifiers(self):
        with self.assertRaises(ValueError):
            parse({
                "schema": 1,
                "device": {
                    "vid": True,
                    "pid": 2,
                    "manufacturer": None,
                    "product": None,
                },
            })


if __name__ == "__main__":
    unittest.main()
