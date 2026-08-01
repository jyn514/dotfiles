#!/usr/bin/env python3

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "install_platform_bundles", ROOT / "lib/install_platform_bundles.py"
)
assert SPEC and SPEC.loader
bundles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundles)


class PlatformBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((ROOT / "install/bundles.json").read_text())

    def test_cpptools_has_glibc_and_musl_assets_for_x64_and_arm64(self) -> None:
        platforms = self.manifest["cpptools"]["platforms"]

        self.assertEqual(
            {
                "linux-aarch64",
                "linux-musl-aarch64",
                "linux-musl-x86_64",
                "linux-x86_64",
            },
            set(platforms),
        )
        self.assertIn("cpptools-linux-arm64.vsix", platforms["linux-aarch64"])
        self.assertIn("cpptools-alpine-arm64.vsix", platforms["linux-musl-aarch64"])

    def test_architecture_aliases_are_normalized(self) -> None:
        with (
            mock.patch.object(bundles.platform, "system", return_value="Linux"),
            mock.patch.object(bundles.platform, "machine", return_value="arm64"),
            mock.patch.object(bundles.Path, "exists", return_value=False),
        ):
            self.assertEqual("linux-aarch64", bundles.platform_key())

    def test_all_platform_bundle_is_used_as_fallback(self) -> None:
        bundle = self.manifest["powershell-editor-services"]

        self.assertEqual(
            bundle["platforms"]["all"],
            bundles.bundle_url(bundle, "windows-aarch64"),
        )

    def test_install_is_atomic_idempotent_and_marks_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            bundle = {
                "destination": ".local/lib/example",
                "executable": "bin/tool",
                "platforms": {"linux-x86_64": "https://example.invalid/tool.zip"},
            }

            def fake_download(_url: str, destination: Path) -> None:
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("bin/tool", "binary")

            with mock.patch.object(bundles, "download", side_effect=fake_download):
                first = bundles.install_bundle(
                    "example", bundle, home=home, current_platform="linux-x86_64"
                )
                second = bundles.install_bundle(
                    "example", bundle, home=home, current_platform="linux-x86_64"
                )

            executable = home / ".local/lib/example/bin/tool"
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertTrue(executable.exists())
            self.assertNotEqual(0, executable.stat().st_mode & 0o111)

    def test_unsupported_bundle_is_skipped_without_creating_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            installed = bundles.install_bundle(
                "example",
                {
                    "destination": ".local/lib/example",
                    "platforms": {"linux-x86_64": "https://example.invalid"},
                },
                home=home,
                current_platform="macos-aarch64",
            )

            self.assertFalse(installed)
            self.assertFalse((home / ".local/lib/example").exists())


if __name__ == "__main__":
    unittest.main()
