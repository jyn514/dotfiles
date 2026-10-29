"""Exercise the real X11 parser and selection protocol on an owned display."""

import base64
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("xclip"),
                     "Xvfb and xclip are required for native clipboard tests")
class XclipTest(unittest.TestCase):
    # A complete PNG, not text that a default STRING target could disguise.
    IMAGE = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
    )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.log = tempfile.TemporaryFile()
        self.addCleanup(self.log.close)
        read_fd, write_fd = os.pipe()
        try:
            self.server = subprocess.Popen(
                [shutil.which("Xvfb"), "-displayfd", str(write_fd),
                 "-screen", "0", "640x480x24", "-nolisten", "tcp"],
                pass_fds=(write_fd,), stdout=self.log, stderr=self.log,
            )
        finally:
            os.close(write_fd)
        self.addCleanup(self.stop_server)
        try:
            self.assertTrue(select.select([read_fd], [], [], 10)[0],
                            "owned Xvfb did not announce readiness")
            number = os.read(read_fd, 32).decode().strip()
            self.assertTrue(number.isdecimal(), "owned Xvfb failed to start")
        finally:
            os.close(read_fd)
        # Exclude all other installed backends, but invoke the actual xclip parser.
        for name in ("xclip", "basename"):
            (self.directory / name).symlink_to(shutil.which(name))
        self.environment = os.environ | {
            "PATH": str(self.directory), "DISPLAY": ":" + number,
        }
        self.owners: list[subprocess.Popen] = []
        self.addCleanup(self.stop_owners)

    def stop_server(self) -> None:
        self.server.terminate()
        self.server.wait(timeout=5)

    def stop_owners(self) -> None:
        for owner in self.owners:
            if owner.poll() is None:
                owner.terminate()
            owner.wait(timeout=5)

    def native(self, selection: str, target: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.directory / "xclip"), "-out", "-selection", selection,
             "-target", target], env=self.environment, capture_output=True,
            timeout=5, check=False,
        )

    def wrapper(self, mode: str, mime: str, selection: str,
                data: bytes | None = None) -> subprocess.CompletedProcess:
        arguments = [str(ROOT / "bin" / mode), "--type", mime]
        if selection == "primary":
            arguments.append("--primary")
        # xclip's default copy process forks. Files avoid inherited capture pipes
        # blocking subprocess.run after the parent exits; the display owns its life.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            result = subprocess.run(
                arguments, input=data, env=self.environment, stdout=output,
                stderr=error, timeout=5, check=False,
            )
            output.seek(0)
            error.seek(0)
            return subprocess.CompletedProcess(arguments, result.returncode,
                                               output.read(), error.read())

    def seed(self, selection: str, mime: str, data: bytes) -> None:
        with tempfile.TemporaryFile() as source:
            source.write(data)
            source.seek(0)
            owner = subprocess.Popen(
                [str(self.directory / "xclip"), "-in", "-quiet", "-selection",
                 selection, "-target", mime], env=self.environment, stdin=source,
                stdout=self.log, stderr=self.log,
            )
        self.owners.append(owner)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.native(selection, mime)
            if result.returncode == 0 and result.stdout == data:
                return
            self.assertIsNone(owner.poll(), "native selection owner exited early")
            time.sleep(0.01)
        self.fail("native selection owner did not become ready")

    def test_copy_advertises_requested_target_and_preserves_binary_data(self) -> None:
        for selection in ("clipboard", "primary"):
            for mime in ("image/png", "application/x-test; charset=utf-8 * [ab]"):
                with self.subTest(selection=selection, mime=mime):
                    copied = self.wrapper("copy", mime, selection, self.IMAGE)
                    self.assertEqual(0, copied.returncode, copied.stderr)
                    targets = self.native(selection, "TARGETS")
                    self.assertEqual(0, targets.returncode, targets.stderr)
                    self.assertIn(mime.encode(), targets.stdout.splitlines())
                    pasted = self.native(selection, mime)
                    self.assertEqual(0, pasted.returncode, pasted.stderr)
                    self.assertEqual(self.IMAGE, pasted.stdout)

    def test_paste_requests_native_image_target_from_each_selection(self) -> None:
        # Seed independently of copy: matching mistakes in the two wrappers must
        # not produce a false-positive round trip. Different payloads catch swaps.
        for selection, data in (("clipboard", self.IMAGE),
                                ("primary", self.IMAGE + b"\0\xff\n")):
            self.seed(selection, "image/png", data)
        for selection, data in (("clipboard", self.IMAGE),
                                ("primary", self.IMAGE + b"\0\xff\n")):
            with self.subTest(selection=selection):
                pasted = self.wrapper("paste", "image/png", selection)
                self.assertEqual(0, pasted.returncode, pasted.stderr)
                self.assertEqual(data, pasted.stdout)

    def test_paste_requests_target_instead_of_default_string(self) -> None:
        # xclip owners answer ordinary targets with the same bytes, even targets
        # they do not advertise. TARGETS is distinct, so a broken paste that asks
        # for the default STRING cannot pass just because the image round-trips.
        for selection in ("clipboard", "primary"):
            with self.subTest(selection=selection):
                self.seed(selection, "image/png", self.IMAGE)
                native = self.native(selection, "TARGETS")
                self.assertEqual(0, native.returncode, native.stderr)
                self.assertIn(b"image/png", native.stdout.splitlines())
                pasted = self.wrapper("paste", "TARGETS", selection)
                self.assertEqual(0, pasted.returncode, pasted.stderr)
                self.assertEqual(native.stdout, pasted.stdout)


if __name__ == "__main__":
    unittest.main()
