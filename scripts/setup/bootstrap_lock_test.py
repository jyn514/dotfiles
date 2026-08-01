#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "install_bootstrap", ROOT / "lib/install_bootstrap.py"
)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapLockTests(unittest.TestCase):
    def test_lock_entries_use_immutable_versions_and_checksums(self) -> None:
        manifest = json.loads((ROOT / "install/bootstrap.lock.json").read_text())
        for entry in manifest["git"].values():
            self.assertEqual(40, len(entry["revision"]))
            int(entry["revision"], 16)
        for entry in manifest["downloads"].values():
            self.assertNotIn("/latest/", entry["url"])
            self.assertEqual(64, len(entry["sha256"]))
            int(entry["sha256"], 16)

    def test_download_is_atomic_and_verifies_contents(self) -> None:
        contents = b"locked contents"
        entry = {
            "url": "https://example.invalid/source",
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [contents, b""]
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "installed"
            with mock.patch.object(bootstrap.urllib.request, "urlopen", return_value=response):
                bootstrap.download(entry, destination)
            self.assertEqual(contents, destination.read_bytes())

    def test_bad_download_does_not_replace_existing_file(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b"bad", b""]
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "installed"
            destination.write_text("old")
            with mock.patch.object(bootstrap.urllib.request, "urlopen", return_value=response):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    bootstrap.download(
                        {"url": "https://example.invalid", "sha256": "0" * 64},
                        destination,
                    )
            self.assertEqual("old", destination.read_text())

    def test_setup_has_no_floating_plugin_clone_or_latest_release(self) -> None:
        setup = (ROOT / "setup.sh").read_text()
        self.assertNotIn("git clone https://github.com/tmux-plugins", setup)
        self.assertNotIn("git clone https://github.com/folke/lazy.nvim", setup)
        self.assertNotIn("releases/download/latest", setup)
        self.assertNotIn("fisher/main/functions/fisher.fish", setup)


if __name__ == "__main__":
    unittest.main()
