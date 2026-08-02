import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/decode-qr"
LOADER = importlib.machinery.SourceFileLoader("decode_qr", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
decode_qr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decode_qr
LOADER.exec_module(decode_qr)


class DecodeQrTests(unittest.TestCase):
    def test_passes_bytes_through_each_program_and_writes_tty(self):
        image = b"\x89PNG\r\n"
        decoded = b"QR-Code:https://example.test/a:b\nraw line\n"
        calls = []

        def runner(arguments, *, input_bytes=None, capture_output=True):
            calls.append((arguments, input_bytes, capture_output))
            outputs = {
                "paste": decode_qr.Result(0, image),
                "zbarimg": decode_qr.Result(0, decoded),
                "copy": decode_qr.Result(0),
            }
            return outputs[arguments[0]]

        with tempfile.TemporaryDirectory() as temporary:
            tty = Path(temporary) / "tty"
            tty.touch()
            self.assertEqual(decode_qr.decode(runner, tty), 0)
            payload = b"https://example.test/a:b\nraw line\n"
            self.assertEqual(tty.read_bytes(), payload)

        self.assertEqual(
            calls,
            [
                (["paste", "--type", "image/png"], None, True),
                (["zbarimg", "-q", "-"], image, True),
                (["copy", "--primary"], payload, False),
            ],
        )

    def test_stops_after_clipboard_failure_and_preserves_status(self):
        runner = mock.Mock(return_value=decode_qr.Result(19, b"partial"))

        self.assertEqual(decode_qr.decode(runner), 19)
        runner.assert_called_once_with(["paste", "--type", "image/png"])

    def test_stops_after_decoder_failure_and_preserves_status(self):
        runner = mock.Mock(
            side_effect=[decode_qr.Result(0, b"image"), decode_qr.Result(7, b"partial")]
        )

        self.assertEqual(decode_qr.decode(runner), 7)
        self.assertEqual(runner.call_count, 2)

    def test_copy_failure_is_returned_after_display(self):
        runner = mock.Mock(
            side_effect=[
                decode_qr.Result(0, b"image"),
                decode_qr.Result(0, b"QR-Code:value\n"),
                decode_qr.Result(31),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            tty = Path(temporary) / "tty"
            tty.touch()
            self.assertEqual(decode_qr.decode(runner, tty), 31)
            self.assertEqual(tty.read_bytes(), b"value\n")

    def test_missing_program_returns_shell_compatible_status(self):
        with mock.patch.object(
            decode_qr.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = decode_qr.run(["missing"])

        self.assertEqual(result.status, 127)
        self.assertIn("could not execute 'missing'", stderr.getvalue())

    def test_rejects_arguments(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(decode_qr.main(["extra"]), 2)


if __name__ == "__main__":
    unittest.main()
