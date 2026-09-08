"""Failed transfers, stale identities, and unsafe paths must never publish a token."""

import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from keychain import validate_token
import sandbox_credentials as credentials

spec = importlib.util.spec_from_file_location("boot_credential", ROOT / "lima/boot-credential.py")
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)
GENERATION = "a" * 32
BOOT = "12345678-1234-1234-1234-123456789abc"


class BootCredentialTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = object.__new__(guest.Cache)
        self.cache.directory = self.root
        self.cache.token = self.root / "github-token"

    def test_complete_transfer_is_private_and_reused_after_lock_exit(self):
        with self.cache.locked():
            self.assertFalse(self.cache.ready())
            self.cache.receive(io.BytesIO(struct.pack("!I", 11) + b"dummy-token"))
        with self.cache.locked():
            self.assertTrue(self.cache.ready())
            self.assertEqual(b"dummy-token", self.cache.token.read_bytes())
            self.assertEqual(0o600, self.cache.token.stat().st_mode & 0o777)

    def test_truncated_oversized_or_line_injected_transfer_never_publishes(self):
        for payload in (b"", b"\0", struct.pack("!I", 20) + b"short",
                        struct.pack("!I", 20000), struct.pack("!I", 4) + b"abc\n",
                        struct.pack("!I", 3) + b"extra"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.cache.receive(io.BytesIO(payload))
                self.assertFalse(self.cache.ready())
                self.assertEqual([], list(self.root.glob(".receive-*")))

    def test_interrupted_publication_removes_unpublished_file(self):
        with patch.object(guest.os, "replace", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                self.cache.receive(io.BytesIO(struct.pack("!I", 5) + b"dummy"))
        self.assertFalse(self.cache.ready())
        self.assertEqual([], list(self.root.glob(".receive-*")))

    def test_symlink_hardlink_and_public_file_are_not_reusable(self):
        other = self.root / "other"
        other.write_bytes(b"dummy")
        other.chmod(0o600)
        self.cache.token.symlink_to(other)
        with self.assertRaises(ValueError):
            self.cache.ready()
        self.cache.token.unlink()
        os.link(other, self.cache.token)
        with self.assertRaises(ValueError):
            self.cache.ready()
        self.cache.token.unlink()
        self.cache.token.write_bytes(b"dummy")
        self.cache.token.chmod(0o644)
        with self.assertRaises(ValueError):
            self.cache.ready()

    def test_stale_generation_or_boot_is_rejected_before_cache_access(self):
        with patch.dict(os.environ, {"SANDBOX_GENERATION": GENERATION}), \
                patch.object(guest.Path, "read_text", return_value=BOOT):
            for generation, boot in (("b" * 32, BOOT), (GENERATION, "f" * 36)):
                with self.assertRaisesRegex(ValueError, "stale"):
                    guest.Cache(generation, boot, self.root)

    def test_disk_backed_cache_is_refused(self):
        with patch.dict(os.environ, {"SANDBOX_GENERATION": GENERATION}), \
                patch.object(guest.Path, "read_text", return_value=BOOT), \
                patch.object(guest.subprocess, "run") as run:
            run.return_value.stdout = "ext4\n"
            with self.assertRaisesRegex(ValueError, "tmpfs"):
                guest.Cache(GENERATION, BOOT, self.root)
        self.assertFalse((self.root / "codex-sandbox-credentials").exists())

    def test_tmpfs_with_active_swap_is_not_treated_as_memory_only(self):
        with patch.object(guest.subprocess, "run") as run, \
                patch.object(guest.Path, "read_text", return_value="Filename Type Size Used Priority\n/swapfile file 1 0 -2\n"):
            run.return_value.stdout = "tmpfs\n"
            with self.assertRaisesRegex(ValueError, "without swap"):
                guest.memory_filesystem(self.root)

    def test_failed_podman_export_cannot_import_partial_output_or_echo_it(self):
        with patch.object(credentials.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = b"dummy-secret"
            run.return_value.stderr = b"dummy-secret"
            with self.assertRaises(ValueError) as result:
                credentials.import_podman_token()
            self.assertNotIn("dummy-secret", str(result.exception))

    def test_invalid_token_errors_do_not_echo_value(self):
        for value in (b"", b"dummy\nsecret", b"dummy\0secret", b"x" * 16385):
            with self.assertRaises(ValueError) as result:
                validate_token(value)
            self.assertNotIn("dummy", str(result.exception))


if __name__ == "__main__":
    unittest.main()
