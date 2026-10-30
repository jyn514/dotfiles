import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
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
        decoded = b"https://example.test/a:b\nVERSION:3.0\nFN:Example Person\n"
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
            payload = decoded
            self.assertEqual(tty.read_bytes(), payload)

        self.assertEqual(
            calls,
            [
                (["paste", "--type", "image/png"], None, True),
                (["zbarimg", "-q", "--raw", "-"], image, True),
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
                decode_qr.Result(0, b"value\n"),
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


def run_entrypoint(entrypoint, image, directory, *, copy_status=0):
    """Run main() with a fresh controlling PTY and file-backed clipboard."""
    import errno
    import fcntl
    import pty
    import termios

    directory = Path(directory)
    image_path = directory / "clipboard.png"
    image_path.write_bytes(image)
    copied = directory / "copied"
    fixture = Path(__file__).parent / "fixtures/clipboard.py"
    for command in ("paste", "copy"):
        shim = directory / command
        shutil.copyfile(fixture, shim)
        shim.chmod(0o755)
    environment = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"],
                       QR_TEST_IMAGE=str(image_path), QR_TEST_COPIED=str(copied),
                       QR_TEST_COPY_STATUS=str(copy_status))
    master, slave = pty.openpty()
    # Preserve byte identity in the disposable terminal (no LF -> CRLF output mapping).
    attributes = termios.tcgetattr(slave)
    attributes[1] &= ~termios.OPOST
    termios.tcsetattr(slave, termios.TCSANOW, attributes)

    def own_terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    try:
        child = subprocess.Popen([sys.executable, str(entrypoint)], stdin=slave,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=environment, preexec_fn=own_terminal)
        os.close(slave)
        slave = -1
        try:
            stdout, stderr = child.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            raise
        displayed = bytearray()
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            displayed.extend(chunk)
        return child.returncode, bytes(displayed), copied.read_bytes() if copied.exists() else None, stdout, stderr
    finally:
        if slave >= 0:
            os.close(slave)
        os.close(master)


@unittest.skipUnless(sys.platform == "linux" and shutil.which("qrencode") and shutil.which("zbarimg"),
                     "native Linux integration needs qrencode and zbarimg")
class NativeDecodeQrTests(unittest.TestCase):
    def encode(self, payload):
        return subprocess.run(["qrencode", "-8", "-o", "-"], input=payload,
                              capture_output=True, check=True).stdout

    def assert_entrypoint(self, image, expected, *, status=0, copy_status=0):
        with tempfile.TemporaryDirectory() as directory:
            actual = run_entrypoint(MODULE_PATH, image, directory, copy_status=copy_status)
        self.assertEqual(actual[:4], (status, expected, expected, b""),
                         actual[4])

    def test_native_multiline_and_unicode_payloads_reach_clipboard_and_tty(self):
        # The producer input is the oracle, not a fake zbarimg output grammar.
        for payload in (b"BEGIN:VCARD\nVERSION:3.0\nFN:Example Person\nNOTE:https://example.test/a:b\nEND:VCARD",
                        b"first:line\nQR-Code:literal prefix\n",
                        "FN:Zoë 日本語".encode()):
            with self.subTest(payload=payload):
                self.assert_entrypoint(self.encode(payload), payload + b"\n")

    def test_native_encoding_decisions_are_not_reinterpreted(self):
        # zbar may transcode byte-mode QR data; the wrapper must preserve its output,
        # not promise identity with arbitrary qrencode input bytes.
        for payload in (b"caf\xe9:a", b"A\x00B\xff:C\r\nD",
                        "FN:Zoë 日本語\r\nQR-Code:literal prefix\n".encode()):
            with self.subTest(payload=payload):
                image = self.encode(payload)
                native = subprocess.run(["zbarimg", "-q", "-"], input=image,
                                        capture_output=True, check=True).stdout
                self.assertTrue(native.startswith(b"QR-Code:"))
                self.assert_entrypoint(image, native.removeprefix(b"QR-Code:"))

    def test_native_decoder_failure_does_not_display_or_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            actual = run_entrypoint(MODULE_PATH, b"not an image", directory)
        native = subprocess.run(["zbarimg", "-q", "-"], input=b"not an image", capture_output=True)
        self.assertNotEqual(native.returncode, 0)
        self.assertEqual(actual[0], native.returncode)
        self.assertEqual(actual[1:4], (b"", None, b""))

    def test_native_copy_failure_preserves_display_and_status(self):
        self.assert_entrypoint(self.encode(b"https://example.test/a:b"),
                               b"https://example.test/a:b\n", status=31, copy_status=31)

    @unittest.skipUnless(shutil.which("magick"), "multi-symbol image composition needs ImageMagick")
    def test_native_multiple_symbols_preserve_each_payload_and_native_order(self):
        payloads = (b"first:https://example.test/a:b", b"second:https://example.test/c:d")
        with tempfile.TemporaryDirectory() as directory:
            images = []
            for index, payload in enumerate(payloads):
                path = Path(directory) / f"{index}.png"
                path.write_bytes(self.encode(payload))
                images.append(str(path))
            image = subprocess.run(["magick", *images, "+append", "png:-"],
                                   capture_output=True, check=True).stdout
        native = subprocess.run(["zbarimg", "-q", "-"], input=image,
                                capture_output=True, check=True).stdout
        records = native.splitlines()
        self.assertCountEqual(records, [b"QR-Code:" + payload for payload in payloads])
        expected = b"".join(record.removeprefix(b"QR-Code:") + b"\n" for record in records)
        self.assert_entrypoint(image, expected)


if __name__ == "__main__":
    unittest.main()
