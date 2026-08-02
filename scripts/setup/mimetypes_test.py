#!/usr/bin/env python3

import importlib.util
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
            SETUP_MIMETYPES_PLATFORM="linux",
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

    def test_dry_run_reports_defaults_without_writing_or_registering(self) -> None:
        home = self.mime / "home"
        binaries = self.mime / "bin"
        data_root = self.mime / "xdg"
        home.mkdir()
        binaries.mkdir()
        data_root.mkdir()
        (data_root / "mime").symlink_to(self.mime, target_is_directory=True)
        log = self.mime / "xdg-mime.log"
        xdg_mime = binaries / "xdg-mime"
        xdg_mime.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$MIME_LOG"\n')
        xdg_mime.chmod(0o755)
        env = os.environ.copy()
        env.update(
            HOME=str(home),
            MIME_LOG=str(log),
            PATH=f"{binaries}:{env['PATH']}",
            SETUP_MIMETYPES_PLATFORM="linux",
            XDG_DATA_DIRS=str(data_root),
            XDG_DATA_HOME=str(self.mime / "empty-data-home"),
        )

        result = subprocess.run(
            [sys.executable, str(ROOT / "lib/setup_mimetypes.py"), "--dry-run"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Neovim MIME defaults:", result.stdout)
        self.assertIn("  application/x-nested-source", result.stdout)
        self.assertFalse(log.exists())
        self.assertFalse(
            (home / ".local/share/applications/nvim-generated.desktop").exists()
        )


class MacOSMimetypeTests(unittest.TestCase):
    def test_only_running_handler_inside_target_app_is_terminated(self) -> None:
        app = Path("/Users/test/Applications/nvim.app")
        processes = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "  10 /Users/test/Applications/nvim.app/Contents/MacOS/file-handler -psn\n"
                "  11 /Applications/Other.app/Contents/MacOS/file-handler\n"
            ),
        )
        with (
            mock.patch.object(subprocess, "run", return_value=processes),
            mock.patch.object(os, "kill") as kill,
        ):
            setup_mimetypes.terminate_running_handler(app)

        kill.assert_called_once_with(10, setup_mimetypes.signal.SIGTERM)

    def test_source_discovery_excludes_stale_managed_utis(self) -> None:
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "public.c-source\n"
                "dev.jyn.source-code.rs\n"
                "dev.jyn.plain-text.toml\n"
            ),
        )
        with mock.patch.object(setup_mimetypes, "run", return_value=completed):
            discovered = setup_mimetypes.filter_source_utis(
                Path("classifier"), ["ignored by mock"]
            )

        self.assertEqual(["public.c-source"], discovered)

    def test_extension_resolution_excludes_stale_managed_utis(self) -> None:
        completed = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "md\tnet.daringfireball.markdown\n"
                "rs\tdev.jyn.source-code.rs\n"
            ),
        )
        with mock.patch.object(setup_mimetypes, "run", return_value=completed):
            resolved = setup_mimetypes.resolve_extension_utis(
                Path("classifier"), ["md", "rs"]
            )

        self.assertEqual({"md": "net.daringfireball.markdown"}, resolved)

    def test_planned_uti_registration_makes_extension_write_redundant(self) -> None:
        missing = setup_mimetypes.missing_extension_associations(
            ["json", "rs"],
            {"json": "public.json"},
            set(),
            ["public.json"],
        )

        self.assertEqual(["rs"], missing)

    def test_policy_does_not_claim_broad_text_web_or_calendar_types(self) -> None:
        policy = setup_mimetypes.load_policy(ROOT / "lib/mimetypes.json")["macos"]

        self.assertNotIn("public.text", policy["editor_utis"])
        self.assertNotIn("html", policy["editor_extension_exceptions"])
        self.assertNotIn("htm", policy["editor_extension_exceptions"])
        self.assertNotIn("ics", policy["editor_extension_exceptions"])
        self.assertIn("toml", policy["editor_extension_exceptions"])

    def test_cleanup_removes_only_neovim_handler_roles(self) -> None:
        preferences = {
            "UnrelatedPreference": True,
            "LSHandlers": [
                {
                    "LSHandlerContentType": "public.html",
                    "LSHandlerRoleAll": "dev.jyn.nvim",
                },
                {
                    "LSHandlerContentType": "public.calendar-event",
                    "LSHandlerRoleEditor": "dev.jyn.nvim",
                    "LSHandlerRoleViewer": "com.apple.Calendar",
                },
                {
                    "LSHandlerContentType": "public.toml",
                    "LSHandlerRoleAll": "com.microsoft.VSCode",
                },
            ],
        }

        cleaned = setup_mimetypes.remove_macos_bundle_handlers(
            preferences, "dev.jyn.nvim"
        )

        self.assertTrue(cleaned["UnrelatedPreference"])
        self.assertEqual(
            [
                {
                    "LSHandlerContentType": "public.calendar-event",
                    "LSHandlerRoleViewer": "com.apple.Calendar",
                },
                {
                    "LSHandlerContentType": "public.toml",
                    "LSHandlerRoleAll": "com.microsoft.VSCode",
                },
            ],
            cleaned["LSHandlers"],
        )

    def test_cleanup_preserves_neovim_roles_already_in_desired_state(self) -> None:
        preferences = {
            "LSHandlers": [
                {
                    "LSHandlerContentType": "public.text",
                    "LSHandlerRoleEditor": "dev.jyn.nvim",
                },
                {
                    "LSHandlerContentType": "net.daringfireball.markdown",
                    "LSHandlerRoleEditor": "dev.jyn.nvim",
                },
            ]
        }

        cleaned = setup_mimetypes.remove_macos_bundle_handlers(
            preferences,
            "dev.jyn.nvim",
            {"net.daringfireball.markdown"},
        )

        self.assertEqual(
            [
                {
                    "LSHandlerContentType": "net.daringfireball.markdown",
                    "LSHandlerRoleEditor": "dev.jyn.nvim",
                }
            ],
            cleaned["LSHandlers"],
        )

    def test_reads_unique_content_types_from_launch_services_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            preferences = Path(temporary_directory) / "handlers.plist"
            with preferences.open("wb") as output:
                plistlib.dump(
                    {
                        "LSHandlers": [
                            {
                                "LSHandlerContentType": "public.toml",
                                "LSHandlerRoleAll": "com.microsoft.VSCode",
                            },
                            {"LSHandlerContentType": "public.toml"},
                            {"LSHandlerContentType": "public.png"},
                            {"LSHandlerContentTag": "rs"},
                            "invalid entry",
                        ]
                    },
                    output,
                )

            handlers = setup_mimetypes.read_macos_handler_utis(preferences)

        self.assertEqual(["public.png", "public.toml"], handlers)

    def test_generated_app_declares_narrow_text_utis_and_native_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "nvim.app"
            setup_mimetypes.write_macos_app(
                app,
                name="Neovim",
                bundle_id="dev.jyn.nvim",
                command=[str(ROOT / "bin/hx-hax")],
                role="Editor",
                utis=["public.plain-text", "public.source-code"],
                launcher_source=ROOT / "lib/file-handler.swift",
                imported_extensions=["rs"],
                imported_parent="public.plain-text",
            )

            with (app / "Contents/Info.plist").open("rb") as plist_file:
                plist = plistlib.load(plist_file)
            document_type = plist["CFBundleDocumentTypes"][0]
            launcher = (app / "Contents/launcher.swift").read_text()

        self.assertEqual("dev.jyn.nvim", plist["CFBundleIdentifier"])
        self.assertEqual(
            [
                "public.plain-text",
                "public.source-code",
                "dev.jyn.nvim.document.rs",
            ],
            document_type["LSItemContentTypes"],
        )
        self.assertEqual("Editor", document_type["CFBundleTypeRole"])
        imported = plist["UTImportedTypeDeclarations"][0]
        self.assertEqual("dev.jyn.nvim.document.rs", imported["UTTypeIdentifier"])
        self.assertEqual(["public.plain-text"], imported["UTTypeConformsTo"])
        self.assertEqual(
            ["rs"], imported["UTTypeTagSpecification"]["public.filename-extension"]
        )
        self.assertEqual([str(ROOT / "bin/hx-hax")], plist["JynCommand"])
        self.assertIn("openFiles filenames", launcher)
        self.assertIn("command + [filename]", launcher)
        self.assertIn("sender.terminate(nil)", launcher)
        self.assertIn('--filter-source-utis', launcher)
        self.assertNotIn("type.conforms(to: .text)", launcher)
        self.assertIn("type.conforms(to: .sourceCode)", launcher)
        self.assertEqual((ROOT / "lib/file-handler.swift").read_text(), launcher)

    def test_generated_fx_app_handles_json_through_terminal_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            app = Path(temporary_directory) / "fx.app"
            setup_mimetypes.write_macos_app(
                app,
                name="fx",
                bundle_id="dev.jyn.fx",
                command=["REAL_EDITOR=fx", str(ROOT / "bin/hx-hax")],
                role="Viewer",
                utis=["public.json"],
                launcher_source=ROOT / "lib/file-handler.swift",
            )

            with (app / "Contents/Info.plist").open("rb") as plist_file:
                plist = plistlib.load(plist_file)

        self.assertEqual("dev.jyn.fx", plist["CFBundleIdentifier"])
        self.assertEqual(
            ["REAL_EDITOR=fx", str(ROOT / "bin/hx-hax")], plist["JynCommand"]
        )
        document_type = plist["CFBundleDocumentTypes"][0]
        self.assertEqual("Viewer", document_type["CFBundleTypeRole"])
        self.assertEqual(["public.json"], document_type["LSItemContentTypes"])


if __name__ == "__main__":
    unittest.main()
