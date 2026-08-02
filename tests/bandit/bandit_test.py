import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "bin/bandit"
LOADER = importlib.machinery.SourceFileLoader("bandit_command", str(MODULE_PATH))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC
bandit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bandit
LOADER.exec_module(bandit)


class BanditTests(unittest.TestCase):
    def test_parses_last_record_at_eof_with_or_without_newline(self):
        for suffix in (b"", b"\n"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    bandit.credential(b"6 - old\n7 - new password-with-hyphen" + suffix),
                    (b"7", b"new password-with-hyphen"),
                )

    def test_trailing_blank_line_is_the_invalid_last_record(self):
        with self.assertRaisesRegex(ValueError, "number - password"):
            bandit.credential(b"7 - password\n\n")

    def test_splits_only_the_first_separator_and_preserves_arbitrary_bytes(self):
        self.assertEqual(
            bandit.credential(b"9 - first - second-\xff\n"),
            (b"9", b"first - second-\xff"),
        )

    def test_rejects_unrepresentable_nul_byte(self):
        with self.assertRaisesRegex(ValueError, "NUL"):
            bandit.credential(b"9 - before\0after\n")

    def test_passes_credentials_as_exact_byte_arguments(self):
        runner = mock.Mock(return_value=bandit.Result(37))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials"
            path.write_bytes(b"12 - tea time-\xff\n")
            self.assertEqual(
                bandit.login(["ignored"], runner=runner, credential_path=path),
                37,
            )

        runner.assert_called_once_with(
            [
                b"sshpass",
                b"-p",
                b"tea time-\xff",
                b"ssh",
                b"-p",
                b"2220",
                b"bandit12@bandit.labs.overthewire.org",
            ]
        )

    def test_missing_or_malformed_file_does_not_launch(self):
        runner = mock.Mock()
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            path = Path(temporary) / "credentials"
            self.assertEqual(bandit.login([], runner=runner, credential_path=path), 1)
            path.write_bytes(b"malformed\n")
            self.assertEqual(bandit.login([], runner=runner, credential_path=path), 1)
        runner.assert_not_called()

    def test_missing_sshpass_returns_shell_compatible_status_without_password(self):
        with mock.patch.object(
            bandit.subprocess,
            "run",
            side_effect=FileNotFoundError("missing"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = bandit.run([b"sshpass", b"-p", b"secret"])

        self.assertEqual(result.status, 127)
        self.assertNotIn("secret", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
