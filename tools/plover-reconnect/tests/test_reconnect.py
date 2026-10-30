import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from plover_reconnect.config import DeviceFingerprint, config_path, parse, read, write
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

    def connected(self, device):
        self.usb.on_connected.call_args.args[0](device)

    def test_start_enumeration_and_unrelated_device_do_not_reset(self):
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            self.connected(Device(9, 9))
        self.engine.reset_machine.assert_not_called()
        self.usb.get_devices.assert_called_once_with()

    def test_matching_events_coalesce_and_reset_after_timer(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            self.connected(Device(1, 2))
            first = FakeTimer.instances[-1]
            self.connected(Device(1, 2))
            second = FakeTimer.instances[-1]
            second.fire()
        self.assertTrue(first.cancelled)
        self.engine.reset_machine.assert_called_once_with()

    def test_superseded_callbacks_cannot_reset_or_clear_current_timer(self):
        write(self.path, DeviceFingerprint(1, 2))
        for fail_cancel in (False, True):
            for old_first in (False, True):
                with self.subTest(fail_cancel=fail_cancel, old_first=old_first):
                    FakeTimer.fail_cancel = fail_cancel
                    self.engine.reset_mock()
                    watcher = self.extension()
                    with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
                        extension, "config_path", return_value=self.path
                    ), mock.patch.object(extension.log, "warning") as warning:
                        watcher.start()
                        self.connected(Device(1, 2))
                        old_timer = FakeTimer.instances[-1]
                        self.connected(Device(1, 2))
                        current_timer = FakeTimer.instances[-1]
                        self.assertTrue(current_timer.started)
                        self.assertEqual(warning.call_count, int(fail_cancel))
                        if old_first:
                            old_timer.fire()
                            self.engine.reset_machine.assert_not_called()
                            self.assertIs(watcher._timer, current_timer)
                        current_timer.fire()
                        self.engine.reset_machine.assert_called_once_with()
                        self.assertIsNone(watcher._timer)
                        old_timer.fire()
                        self.engine.reset_machine.assert_called_once_with()
                        self.assertIsNone(watcher._timer)

    def test_stop_invalidates_pending_timer(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            self.connected(Device(1, 2))
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
            self.connected(Device(1, 2))
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
            self.connected(Device(1, 2))
            old_timer = FakeTimer.instances[-1]
            watcher.stop()
            watcher.start()
            old_timer.fire()
        self.engine.reset_machine.assert_not_called()

    def test_old_registered_callback_cannot_replace_fresh_timer_after_restart(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            old_callback = self.usb.on_connected.call_args.args[0]
            watcher.stop()
            watcher.start()
            self.connected(Device(1, 2))
            current_timer = FakeTimer.instances[-1]
            old_callback(Device(1, 2))
            self.assertEqual(len(FakeTimer.instances), 1)
            self.assertFalse(current_timer.cancelled)
            current_timer.fire()
        self.engine.reset_machine.assert_called_once_with()

    def test_callback_reading_configuration_cannot_enter_restarted_lifecycle(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        reading = threading.Event()
        resume = threading.Event()

        def delayed_read(path):
            fingerprint = read(path)
            if not reading.is_set():
                reading.set()
                if not resume.wait(5):
                    raise RuntimeError("configuration read was not released")
            return fingerprint

        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ), mock.patch.object(extension, "read", side_effect=delayed_read), ThreadPoolExecutor(
            max_workers=1
        ) as pool:
            watcher.start()
            old_callback = self.usb.on_connected.call_args.args[0]
            delivery = pool.submit(old_callback, Device(1, 2))
            try:
                self.assertTrue(reading.wait(5))
                watcher.stop()
                watcher.start()
                self.connected(Device(1, 2))
                current_timer = FakeTimer.instances[-1]
            finally:
                resume.set()
                delivery.result(timeout=5)
            self.assertEqual(len(FakeTimer.instances), 1)
            self.assertFalse(current_timer.cancelled)
            current_timer.fire()
        self.engine.reset_machine.assert_called_once_with()

    def test_selection_changes_apply_to_next_attachment_not_pending_reset(self):
        write(self.path, DeviceFingerprint(1, 2))
        watcher = self.extension()
        with mock.patch.object(extension, "usb", self.usb), mock.patch.object(
            extension, "config_path", return_value=self.path
        ):
            watcher.start()
            self.connected(Device(1, 2))
            pending_timer = FakeTimer.instances[-1]
            write(self.path, DeviceFingerprint(3, 4))
            pending_timer.fire()
            self.engine.reset_machine.assert_called_once_with()
            self.connected(Device(1, 2))
            self.assertEqual(len(FakeTimer.instances), 1)
            self.connected(Device(3, 4))
            FakeTimer.instances[-1].fire()
        self.assertEqual(self.engine.reset_machine.call_count, 2)

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
            self.connected(Device(1, 2))
        self.engine.reset_machine.assert_not_called()

    def test_configuration_round_trips_optional_labels(self):
        fingerprint = DeviceFingerprint(1, 2, "Maker", "Model")
        write(self.path, fingerprint)
        self.assertEqual(read(self.path), fingerprint)

    def test_config_path_uses_plover_oslayer_config(self):
        plover = types.ModuleType("plover")
        oslayer = types.ModuleType("plover.oslayer")
        config = types.ModuleType("plover.oslayer.config")
        config.CONFIG_DIR = self.temp.name
        with mock.patch.dict(sys.modules, {
            "plover": plover,
            "plover.oslayer": oslayer,
            "plover.oslayer.config": config,
        }):
            self.assertEqual(config_path(), self.path)

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
