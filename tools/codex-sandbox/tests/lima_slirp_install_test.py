import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "lima/install-slirp4netns.py"
spec = importlib.util.spec_from_file_location("slirp_install", SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
RELEASE = b"owned fixture release"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / "slirp4netns"
        digest = patch.object(installer, "SHA256", hashlib.sha256(RELEASE).hexdigest())
        digest.start()
        self.addCleanup(digest.stop)

    def test_verified_install_is_executable_and_reboot_needs_no_download(self):
        with patch.object(installer, "urlopen", return_value=io.BytesIO(RELEASE)) as fetch:
            installer.install(self.destination)
            installer.install(self.destination)
        self.assertEqual(RELEASE, self.destination.read_bytes())
        self.assertEqual(0o755, self.destination.stat().st_mode & 0o777)
        fetch.assert_called_once()

    def test_corrupt_download_never_reaches_executable_path(self):
        with patch.object(installer, "urlopen", return_value=io.BytesIO(b"corrupt release")):
            with self.assertRaisesRegex(ValueError, "checksum"):
                installer.install(self.destination)
        self.assertEqual([], list(self.destination.parent.iterdir()))

    def test_interrupted_download_leaves_no_installation(self):
        class Interrupted(io.BytesIO):
            def read(self, size=-1):
                if self.tell():
                    raise OSError("download interrupted")
                return super().read(4)

        with patch.object(installer, "urlopen", return_value=Interrupted(RELEASE)):
            with self.assertRaisesRegex(OSError, "interrupted"):
                installer.install(self.destination)
        self.assertEqual([], list(self.destination.parent.iterdir()))

    def test_existing_different_binary_is_preserved(self):
        self.destination.write_bytes(b"operator-installed binary")
        self.destination.chmod(0o755)
        with patch.object(installer, "urlopen") as fetch:
            with self.assertRaisesRegex(ValueError, "checksum"):
                installer.install(self.destination)
        fetch.assert_not_called()
        self.assertEqual(b"operator-installed binary", self.destination.read_bytes())


if __name__ == "__main__":
    unittest.main()
