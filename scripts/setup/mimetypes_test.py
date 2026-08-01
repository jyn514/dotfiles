#!/usr/bin/env python3

import importlib.util
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "setup_mimetypes", ROOT / "lib/setup_mimetypes.py"
)
assert SPEC and SPEC.loader
setup_mimetypes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup_mimetypes)


class LinuxMimetypeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.mime = Path(self.temporary_directory.name)
        (self.mime / "types").write_text(
            "application/json\n"
            "application/x-nested-source\n"
            "application/x-source\n"
            "image/svg+xml\n"
            "text/plain\n"
            "text/x-rust\n"
        )
        (self.mime / "subclasses").write_text(
            "application/x-source text/plain\n"
            "application/x-nested-source application/x-source\n"
        )
        self.policy = {
            "editor_mime_prefixes": ["text/"],
            "editor_mime_roots": ["text/plain"],
            "editor_mime_exceptions": ["application/javascript"],
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_discovers_text_types_without_naming_them_in_policy(self) -> None:
        discovered = setup_mimetypes.discover_editor_mimes(self.policy, [self.mime])

        self.assertIn("text/x-rust", discovered)

    def test_discovers_transitive_descendants_of_plain_text(self) -> None:
        discovered = setup_mimetypes.discover_editor_mimes(self.policy, [self.mime])

        self.assertIn("application/x-source", discovered)
        self.assertIn("application/x-nested-source", discovered)

    def test_includes_exceptions_but_not_unrelated_types(self) -> None:
        discovered = setup_mimetypes.discover_editor_mimes(self.policy, [self.mime])

        self.assertIn("application/javascript", discovered)
        self.assertNotIn("application/json", discovered)
        self.assertNotIn("image/svg+xml", discovered)

    def test_missing_database_still_returns_roots_and_exceptions(self) -> None:
        discovered = setup_mimetypes.discover_editor_mimes(self.policy, [])

        self.assertEqual(["application/javascript", "text/plain"], discovered)

    def test_generated_desktop_advertises_every_discovered_type(self) -> None:
        template = self.mime / "nvim.desktop"
        destination = self.mime / "generated/nvim.desktop"
        template.write_text("[Desktop Entry]\nExec=hx-hax %F\nMimeType=text/plain;\n")

        setup_mimetypes.write_linux_desktop(
            template,
            destination,
            ["application/x-source", "text/plain", "text/x-rust"],
        )

        generated = destination.read_text()
        self.assertIn("Exec=hx-hax %F", generated)
        self.assertIn(
            "MimeType=application/x-source;text/plain;text/x-rust;", generated
        )
        self.assertNotIn("MimeType=text/plain;\n", generated)

    def test_setup_registers_discovered_and_special_case_handlers(self) -> None:
        home = self.mime / "home"
        binaries = self.mime / "bin"
        data_root = self.mime / "xdg"
        home.mkdir()
        binaries.mkdir()
        data_root.mkdir()
        (data_root / "mime").symlink_to(self.mime, target_is_directory=True)
        log = self.mime / "xdg-mime.log"
        for command in ("nvim", "fx"):
            executable = binaries / command
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
        xdg_mime = binaries / "xdg-mime"
        xdg_mime.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MIME_LOG"\n')
        xdg_mime.chmod(0o755)
        xdg_settings = binaries / "xdg-settings"
        xdg_settings.write_text("#!/bin/sh\nprintf 'browser.desktop\\n'\n")
        xdg_settings.chmod(0o755)
        env = os.environ.copy()
        env.update(
            HOME=str(home),
            MIME_LOG=str(log),
            PATH=f"{binaries}:{env['PATH']}",
            XDG_DATA_DIRS=str(data_root),
            XDG_DATA_HOME=str(self.mime / "empty-data-home"),
        )

        result = subprocess.run(
            ["sh", "setup.sh", "mimetypes"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        registrations = log.read_text().splitlines()
        self.assertIn(
            "default nvim-generated.desktop application/x-nested-source",
            registrations,
        )
        self.assertIn(
            "default nvim-generated.desktop text/x-rust", registrations
        )
        self.assertIn("default fx-usercreated-1.desktop application/json", registrations)
        self.assertIn("default browser.desktop image/svg+xml", registrations)
        desktop = home / ".local/share/applications/nvim-generated.desktop"
        self.assertIn("application/x-nested-source", desktop.read_text())


class MacOSMimetypeTests(unittest.TestCase):
    def test_generated_app_declares_broad_text_utis_and_native_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "nvim.app"
            setup_mimetypes.write_macos_app(
                app,
                {
                    "editor_utis": ["public.text", "public.source-code"],
                    "editor_extension_exceptions": ["rs"],
                },
            )

            with (app / "Contents/Info.plist").open("rb") as plist_file:
                plist = plistlib.load(plist_file)
            document_type = plist["CFBundleDocumentTypes"][0]
            launcher = (app / "Contents/launcher.swift").read_text()

        self.assertEqual("dev.jyn.nvim", plist["CFBundleIdentifier"])
        self.assertEqual(
            ["public.text", "public.source-code", "dev.jyn.source-code.rs"],
            document_type["LSItemContentTypes"],
        )
        self.assertEqual("Editor", document_type["CFBundleTypeRole"])
        imported = plist["UTImportedTypeDeclarations"][0]
        self.assertEqual("dev.jyn.source-code.rs", imported["UTTypeIdentifier"])
        self.assertEqual(
            ["rs"], imported["UTTypeTagSpecification"]["public.filename-extension"]
        )
        self.assertIn("openFiles filenames", launcher)
        self.assertIn('["hx-hax", filename]', launcher)


if __name__ == "__main__":
    unittest.main()
