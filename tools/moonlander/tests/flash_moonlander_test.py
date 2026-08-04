import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[3]
TOOL_DIR = ROOT / "tools/moonlander"
sys.path.insert(0, str(TOOL_DIR))
import flash_moonlander  # noqa: E402


def keymap_source():
    return (
        "SEND_STRING(SS_LCTL(SS_LSFT(SS_TAP(X_U))) "
        "SS_TAP(X_A) SS_TAP(X_E) SS_TAP(X_ENTER)); KC_F13\n"
        "bool process_record_user(uint16_t keycode, keyrecord_t *record) {\n"
        "  return true;\n"
        "}\n"
    )


def archive_bytes(root="zsa_moonlander_test_source", keymap=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("README.md", "Oryx build archive")
        archive.writestr("zsa_moonlander_reva_test.bin", b"firmware")
        archive.writestr(f"{root}/keymap.c", keymap or keymap_source())
        archive.writestr(f"{root}/rules.mk", "")
        archive.writestr(f"{root}/config.h", "")
    return output.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_rejects_traversal_absolute_paths_and_symlinks(self):
        cases = ["../escape", "/absolute"]
        for name in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(name, "bad")
                with self.assertRaises(flash_moonlander.FlashError):
                    flash_moonlander.validate_archive(path)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "symlink.zip"
            member = zipfile.ZipInfo("zsa_moonlander_test_source/link")
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(member, "elsewhere")
            with self.assertRaises(flash_moonlander.FlashError):
                flash_moonlander.validate_archive(path)

    def test_failed_download_preserves_existing_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "revision.zip"
            original = b"not a zip, but still the previous cache"
            path.write_bytes(original)

            def failed_download(_url):
                raise OSError("network unavailable")

            with self.assertRaises(flash_moonlander.FlashError):
                flash_moonlander.ensure_archive("revision", path, failed_download)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_valid_cache_is_reused_without_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "revision.zip"
            path.write_bytes(archive_bytes())

            flash_moonlander.ensure_archive(
                "revision", path, mock.Mock(side_effect=AssertionError("downloaded"))
            )


class FlashTests(unittest.TestCase):
    def test_compile_only_installs_patched_source_and_compiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            qmk_home = home / "qmk"
            keymaps = qmk_home / "keyboards/zsa/moonlander/keymaps"
            keymaps.mkdir(parents=True)
            destination = keymaps / "layout-revision"
            destination.mkdir()
            (destination / "old").write_text("preserve until install")
            archive = home / "source.zip"
            archive.write_bytes(archive_bytes())
            calls = []

            def fake_run(arguments, **kwargs):
                calls.append((arguments, kwargs))
                return 0

            environment = {
                "HOME": str(home),
                "QMK_HOME": str(qmk_home),
                "COMPILE_ONLY": "1",
            }
            with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
                flash_moonlander, "latest_revision", return_value=("layout", "revision")
            ), mock.patch.object(
                flash_moonlander, "ensure_archive", return_value=archive
            ), mock.patch.object(
                flash_moonlander, "qmk_prefix", return_value=["qmk"]
            ), mock.patch.object(flash_moonlander, "run", side_effect=fake_run):
                self.assertEqual(flash_moonlander.flash([]), 0)

            self.assertEqual(len(calls), 2)
            self.assertEqual(
                calls[0][0], [str(TOOL_DIR / "sync-moonlander"), "--pull"]
            )
            self.assertEqual(
                calls[1][0],
                ["qmk", "compile", "-kb", "zsa/moonlander/reva", "-km", "layout-revision"],
            )
            self.assertFalse((destination / "old").exists())
            self.assertIn("UC_NEXT", (destination / "keymap.c").read_text())
            self.assertIn("UNICODE_COMMON = yes", (destination / "rules.mk").read_text())
            self.assertIn("UNICODE_SELECTED_MODES", (destination / "config.h").read_text())
            self.assertEqual(list(keymaps.glob(".layout-revision.*")), [])

    def test_patch_failure_preserves_existing_keymap(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            qmk_home = home / "qmk"
            keymaps = qmk_home / "keyboards/zsa/moonlander/keymaps"
            destination = keymaps / "layout-revision"
            destination.mkdir(parents=True)
            marker = destination / "old"
            marker.write_text("still here")
            archive = home / "source.zip"
            archive.write_bytes(archive_bytes(keymap="KC_F13\n"))

            with mock.patch.dict(
                os.environ,
                {"HOME": str(home), "QMK_HOME": str(qmk_home)},
                clear=True,
            ), mock.patch.object(
                flash_moonlander, "latest_revision", return_value=("layout", "revision")
            ), mock.patch.object(
                flash_moonlander, "ensure_archive", return_value=archive
            ), mock.patch.object(
                flash_moonlander, "qmk_prefix", return_value=["qmk"]
            ), mock.patch.object(flash_moonlander, "run", return_value=0):
                with self.assertRaises(flash_moonlander.FlashError):
                    flash_moonlander.flash([])

            self.assertEqual(marker.read_text(), "still here")

    def test_command_failure_status_is_preserved(self):
        with mock.patch.object(flash_moonlander, "run", return_value=23):
            self.assertEqual(flash_moonlander.main([]), 23)


if __name__ == "__main__":
    unittest.main()
