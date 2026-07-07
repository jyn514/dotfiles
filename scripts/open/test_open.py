#!/usr/bin/env python3
"""Unit tests for bin/open and bin/hx-hax behavior."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import argparse
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from urllib.parse import quote


REPO = Path(__file__).resolve().parents[2]
DEFAULT_HX_HAX = REPO / "bin" / "hx-hax"


class OpenScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="open-test-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    @staticmethod
    def real(path: Path) -> str:
        return str(path.resolve())

    def load_open_module(self, *, real_editor: str | None = None):
        old_real_editor = os.environ.get("REAL_EDITOR")
        if real_editor is None:
            os.environ.pop("REAL_EDITOR", None)
        else:
            os.environ["REAL_EDITOR"] = real_editor
        try:
            loader = importlib.machinery.SourceFileLoader(
                f"open_under_test_{id(self)}", str(DEFAULT_HX_HAX)
            )
            spec = importlib.util.spec_from_loader(loader.name, loader)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            return module
        finally:
            if old_real_editor is None:
                os.environ.pop("REAL_EDITOR", None)
            else:
                os.environ["REAL_EDITOR"] = old_real_editor

    def test_split_line_decodes_file_url_space(self) -> None:
        target = self.root / "space name.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(
            module.split_line(f"file://{quote(str(target), safe='/')}:4"),
            [self.real(target), "4"],
        )

    def test_join_line_for_nvim_and_kak(self) -> None:
        nvim_module = self.load_open_module()
        kak_module = self.load_open_module(real_editor="kak")

        self.assertEqual(
            nvim_module.join_line(["/tmp/note.txt", "4", "2"]),
            ["+normal!4G2|", "/tmp/note.txt"],
        )
        self.assertEqual(
            kak_module.join_line(["/tmp/note.txt", "4"]),
            ["/tmp/note.txt", "+4"],
        )

    def test_default_is_editor_uses_literal_editor_name(self) -> None:
        module = self.load_open_module(real_editor="a.n")

        self.assertTrue(module.default_is_editor("a.n.desktop"))
        self.assertFalse(module.default_is_editor("axon.desktop"))

    def test_plain_url_uses_xdg_open(self) -> None:
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen(["https://example.test/path:12"]), 0)

        os_open.assert_called_once_with(["https://example.test/path:12"])

    def test_missing_args_prints_literal_usage_and_fails(self) -> None:
        module = self.load_open_module()

        with (
            mock.patch.object(module, "refresh_path_from_profile"),
            mock.patch.object(module.sys, "argv", ["open"]),
        ):
            self.assertEqual(module.main([]), 1)

    def test_plain_file_without_line_uses_xdg_open(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen([str(target)]), 0)

        os_open.assert_called_once_with([str(target)])

    def test_os_open_returns_xdg_open_exit_code(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        completed = subprocess.CompletedProcess(["xdg-open", str(target)], 23)
        with (
            mock.patch.object(module, "cmdexists", return_value=True),
            mock.patch.object(module.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(module.os_open([str(target)]), 23)

        run.assert_called_once_with(["xdg-open", str(target)], check=False)

    def test_broken_profile_path_refresh_does_not_prevent_opening(self) -> None:
        module = self.load_open_module()
        original_path = "/still/here"
        failed = subprocess.CompletedProcess(
            ["bash", "-c", ". ~/.profile; echo $PATH"], 1, stdout=""
        )

        with (
            mock.patch.dict(module.os.environ, {"PATH": original_path}),
            mock.patch.object(module, "run", return_value=failed),
        ):
            module.refresh_path_from_profile()
            self.assertEqual(module.os.environ["PATH"], original_path)

    def test_plain_multiple_args_are_forwarded_to_xdg_open(self) -> None:
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("tea\n", encoding="utf-8")
        second.write_text("water\n", encoding="utf-8")
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen(["--reveal", str(first), str(second)]), 0)

        os_open.assert_called_once_with(["--reveal", str(first), str(second)])

    def test_tilde_is_expanded_before_os_open(self) -> None:
        home = self.root / "home"
        target = home / "note.txt"
        target.parent.mkdir()
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.dict(module.os.environ, {"HOME": str(home)}),
            mock.patch.object(module, "os_open", return_value=0) as os_open,
        ):
            self.assertEqual(module.xdgopen(["~/note.txt"]), 0)

        os_open.assert_called_once_with([str(target)])

    def test_non_editor_default_opens_file_without_line_suffix(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="org.example.Viewer.desktop"),
            mock.patch.object(module, "os_open", return_value=0) as os_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:7"]), 0)

        os_open.assert_called_once_with([self.real(target)])

    def test_real_editor_nvim_matches_unset_editor_behavior(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="nvim")

        with (
            mock.patch.object(module, "default_app", return_value="nvim.desktop"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:10"]), 0)

        tmux_open.assert_called_once_with(["+normal!10G|", self.real(target)])

    def test_real_editor_as_absolute_path_matches_desktop_basename(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        editor = self.root / "editors" / "nvim"
        editor.parent.mkdir()
        module = self.load_open_module(real_editor=str(editor))

        with (
            mock.patch.object(module, "default_app", return_value="nvim.desktop"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:10"]), 0)

        tmux_open.assert_called_once_with([f"{self.real(target)}:10"])

    def test_editor_name_regex_metacharacters_do_not_match_unrelated_default(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="a.n")

        with (
            mock.patch.object(module, "default_app", return_value="axon.desktop"),
            mock.patch.object(module, "os_open", return_value=0) as os_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:10"]), 0)

        os_open.assert_called_once_with([self.real(target)])

    def test_dash_leading_filename_with_line_is_passed_to_editor(self) -> None:
        target = self.root / "-note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:3"))),
            ["+normal!3G|", "--", self.real(target)],
        )

    def test_directory_path_with_line_is_canonicalized(self) -> None:
        target = self.root / "notes"
        target.mkdir()
        module = self.load_open_module()

        self.assertEqual(module.split_line(f"{target}:3"), [self.real(target), "3"])

    def test_symlink_path_with_line_is_resolved(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        link_target = self.root / "link.txt"
        link_target.symlink_to(target)
        module = self.load_open_module()

        self.assertEqual(module.split_line(f"{link_target}:3"), [self.real(target), "3"])

    def test_relative_nonexistent_file_with_line_becomes_absolute(self) -> None:
        module = self.load_open_module()

        self.assertEqual(
            module.split_line("missing-relative.txt:3"),
            [str(REPO / "missing-relative.txt"), "3"],
        )

    def test_file_url_localhost_with_line_uses_uri_path(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(module.split_line(f"file://localhost{target}:3"), [self.real(target), "3"])

    def test_multi_dot_extension_uses_last_extension_for_duti(self) -> None:
        target = self.root / "archive.tar.gz"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with mock.patch.object(
            module, "run_stdout", return_value="org.example.Archive.desktop\n"
        ) as run_stdout:
            self.assertEqual(module.duti_default(str(target)), "org.example.Archive.desktop")

        run_stdout.assert_called_once_with(["duti", "-x", "gz"])

    def test_non_editor_default_with_multiple_args_preserves_preceding_args(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="org.example.Viewer.desktop"),
            mock.patch.object(module, "os_open", return_value=0) as os_open,
        ):
            self.assertEqual(module.xdgopen(["--first", "--second", f"{target}:7"]), 0)

        os_open.assert_called_once_with(["--first", "--second", self.real(target)])

    def test_existing_filename_ending_colon_digits_is_not_split(self) -> None:
        target = self.root / "note:7"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen([str(target)]), 0)

        os_open.assert_called_once_with([self.real(target)])

    def test_nonexistent_file_with_line_keeps_uncanonicalized_path(self) -> None:
        target = self.root / "missing.txt"
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="nvim.desktop"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:12"]), 0)

        tmux_open.assert_called_once_with(["+normal!12G|", self.real(target)])

    def test_file_url_without_line_uses_os_open(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen([f"file://{target}"]), 0)

        os_open.assert_called_once_with([f"file://{target}"])

    def test_file_url_with_escaped_space_and_line_through_open_is_not_split(self) -> None:
        target = self.root / "space name.txt"
        target.write_text("tea\n", encoding="utf-8")
        escaped = quote(str(target), safe="/")
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen([f"file://{escaped}:5"]), 0)

        os_open.assert_called_once_with([f"file://{escaped}:5"])

    def test_uppercase_url_scheme_is_not_split_as_line_number(self) -> None:
        module = self.load_open_module()

        with mock.patch.object(module, "os_open", return_value=0) as os_open:
            self.assertEqual(module.xdgopen(["HTTPS://example.test/path:12"]), 0)

        os_open.assert_called_once_with(["HTTPS://example.test/path:12"])

    def test_uppercase_file_url_scheme_through_editor_hax_is_decoded(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(module.split_line(f"FILE://{target}:5"), [self.real(target), "5"])

    def test_xdg_mime_failure_falls_back_to_os_open(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value=""),
            mock.patch.object(module, "os_open", return_value=0) as os_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:8"]), 0)

        os_open.assert_called_once_with([self.real(target)])

    def test_gio_without_default_application_falls_back_to_os_open(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value=""),
            mock.patch.object(module, "os_open", return_value=0) as os_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:8"]), 0)

        os_open.assert_called_once_with([self.real(target)])

    def test_xdg_mime_default_is_used_when_duti_and_gio_are_absent(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="nvim.desktop\n"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:8"]), 0)

        tmux_open.assert_called_once_with(["+normal!8G|", self.real(target)])

    def test_gio_default_is_used_when_duti_is_absent(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="nvim.desktop\n"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:8"]), 0)

        tmux_open.assert_called_once_with(["+normal!8G|", self.real(target)])

    def test_macos_open_fallback_removes_script_directory_from_path(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()
        bin_dir = str(DEFAULT_HX_HAX.parent)
        completed = subprocess.CompletedProcess(["open", str(target)], 0)

        with (
            mock.patch.object(module, "cmdexists", return_value=False),
            mock.patch.dict(module.os.environ, {"PATH": f"{bin_dir}{os.pathsep}/usr/bin"}),
            mock.patch.object(module.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(module.os_open([str(target)]), 0)
            self.assertEqual(module.os.environ["PATH"], "/usr/bin")

        run.assert_called_once_with(["open", str(target)], check=False)

    def test_editor_default_sends_nvim_position_to_tmux(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="nvim.desktop"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:7:3"]), 0)

        tmux_open.assert_called_once_with(["+normal!7G3|", self.real(target)])

    def test_editor_default_matches_bare_editor_name(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="nvim\n"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:7"]), 0)

        tmux_open.assert_called_once_with(["+normal!7G|", self.real(target)])

    def test_hx_default_matches_helix_desktop(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "default_app", return_value="Helix.desktop\n"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:7"]), 0)

        tmux_open.assert_called_once_with([f"{self.real(target)}:7"])

    def test_textedit_default_is_treated_as_editor_like(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        with (
            mock.patch.object(module, "default_app", return_value="TextEdit\n"),
            mock.patch.object(module, "open_in_tmux_editor", return_value=0) as tmux_open,
        ):
            self.assertEqual(module.xdgopen([f"{target}:7"]), 0)

        tmux_open.assert_called_once_with(["+normal!7G|", self.real(target)])

    def test_trailing_colon_is_included_in_nvim_normal_command(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:6:"))),
            ["+normal!6G:|", self.real(target)],
        )

    def test_editor_hax_without_line_execs_editor_with_file_only(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(str(target)))),
            [self.real(target)],
        )

    def test_editor_hax_without_args_execs_editor(self) -> None:
        module = self.load_open_module()

        with (
            mock.patch.object(module, "refresh_path_from_profile"),
            mock.patch.object(module.sys, "argv", ["editor-hax"]),
            mock.patch.object(module.os, "execvp") as execvp,
        ):
            module.main([])
        execvp.assert_called_once_with(module.EDITOR, [module.EDITOR])

    def test_editor_hax_rejects_multiple_args(self) -> None:
        module = self.load_open_module()

        with (
            mock.patch.object(module, "refresh_path_from_profile"),
            mock.patch.object(module.sys, "argv", ["editor-hax"]),
            mock.patch.object(module.os, "execvp") as execvp,
        ):
            self.assertEqual(module.main(["README.md:3", "LICENSE:2"]), 2)
        execvp.assert_not_called()

    def test_editor_hax_preserves_shell_sensitive_filename_characters(self) -> None:
        target = self.root / "semi;pipe|quote'.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:4"))),
            ["+normal!4G|", self.real(target)],
        )

    def test_file_url_with_position_is_decoded_for_editor(self) -> None:
        target = self.root / "space name.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module()

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"file://{target}:11:2"))),
            ["+normal!11G2|", self.real(target)],
        )

    def test_kak_editor_position_argument_order(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="kak")

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:9:5"))),
            [self.real(target), "+9:5"],
        )

    def test_kak_editor_line_only_argument_order(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="kak")

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:9"))),
            [self.real(target), "+9"],
        )

    def test_non_special_editor_gets_file_line_column_joined(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="micro")

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:9:5"))),
            [f"{self.real(target)}:9:5"],
        )

    def test_non_special_editor_line_only_gets_file_line_joined(self) -> None:
        target = self.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        module = self.load_open_module(real_editor="micro")

        self.assertEqual(
            module.editor_exec_args(module.join_line(module.split_line(f"{target}:9"))),
            [f"{self.real(target)}:9"],
        )

    def test_hx_hax_reuses_existing_tmux_pane(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "run_stdout", side_effect=["@2\n", "%4\n", "0\n"]),
            mock.patch.object(module, "activate_window_if_needed"),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            self.assertEqual(module.open_in_tmux_editor([f"{self.real(REPO / 'README.md')}:3"]), 0)

        run.assert_has_calls(
            [
                mock.call(["tmux", "send-keys", "-t", "%4", "Escape"], check=False),
                mock.call(
                    [
                        "tmux",
                        "send-keys",
                        "-t",
                        "%4",
                        f": open {self.real(REPO / 'README.md')}:3",
                        "Enter",
                    ],
                    check=False,
                ),
                mock.call(["tmux", "select-pane", "-t", "%4", "-Z"], check=False),
            ]
        )
        self.assertNotIn(
            mock.call(["tmux", "send-keys", "-t", "%4", "-X", "cancel"], check=False),
            run.mock_calls,
        )

    def test_hx_hax_cancels_tmux_mode_before_reusing_existing_pane(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "run_stdout", side_effect=["@2\n", "%4\n", "1\n"]),
            mock.patch.object(module, "activate_window_if_needed"),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            self.assertEqual(module.open_in_tmux_editor([f"{self.real(REPO / 'README.md')}:3"]), 0)

        run.assert_any_call(["tmux", "send-keys", "-t", "%4", "-X", "cancel"], check=False)

    def test_hx_hax_with_no_args_sends_empty_open_command(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "run_stdout", side_effect=["@2\n", "%4\n", "0\n"]),
            mock.patch.object(module, "activate_window_if_needed"),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            self.assertEqual(module.open_in_tmux_editor([""]), 0)

        run.assert_any_call(["tmux", "send-keys", "-t", "%4", ": open ", "Enter"], check=False)

    def test_hx_hax_rejects_multiple_args(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "refresh_path_from_profile"),
            mock.patch.object(module.sys, "argv", ["hx-hax"]),
            mock.patch.object(module, "open_in_tmux_editor") as tmux_open,
        ):
            self.assertEqual(module.main(["README.md:3", "LICENSE:2"]), 2)
        tmux_open.assert_not_called()

    def test_hx_hax_whitespace_pane_output_counts_as_no_pane(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "run_stdout", side_effect=["@2\n", "   \n"]),
            mock.patch.object(module, "activate_window_if_needed"),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            self.assertEqual(module.open_in_tmux_editor([f"{self.real(REPO / 'README.md')}:4"]), 0)

        run.assert_called_once_with(
            [
                "tmux",
                "split-window",
                "-h",
                "-P",
                "-F",
                '"#{pane_id}"',
                "hx",
                f"{self.real(REPO / 'README.md')}:4",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_hx_hax_activates_window_with_xdotool_when_display_is_set(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.dict(module.os.environ, {"DISPLAY": ":1", "WINDOWID": "777"}),
            mock.patch.object(module, "cmdexists", return_value=True),
            mock.patch.object(module, "run_stdout", side_effect=["999\n", "123\n", "i3---zsh\n"]),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            module.activate_window_if_needed("%4")

        run.assert_called_once_with(
            ["tmux", "run-shell", "-t", "%4", "xdotool", "windowactivate", "777"],
            check=False,
        )

    def test_hx_hax_does_not_activate_window_when_active_window_is_tmux(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.dict(module.os.environ, {"DISPLAY": ":1", "WINDOWID": "777"}),
            mock.patch.object(module, "cmdexists", return_value=True),
            mock.patch.object(module, "run_stdout", side_effect=["999\n", "123\n", "i3---tmux---zsh\n"]),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            module.activate_window_if_needed("%4")

        run.assert_not_called()

    def test_hx_hax_does_not_activate_window_when_windowid_is_missing(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.dict(module.os.environ, {"DISPLAY": ":1"}, clear=True),
            mock.patch.object(module, "cmdexists", return_value=True),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            module.activate_window_if_needed("%4")

        run.assert_not_called()

    @unittest.skipUnless(sys.platform == "darwin", "Darwin-only osascript branch")
    def test_hx_hax_on_darwin_activates_iterm_with_osascript(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.dict(module.os.environ, {}, clear=True),
            mock.patch.object(module.sys, "platform", "darwin"),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            module.activate_window_if_needed("%4")

        argv = run.call_args.args[0]
        self.assertEqual(argv[:2], ["osascript", "-e"])
        self.assertFalse(argv[2].startswith("\n"))

    def test_hx_hax_creates_tmux_pane_when_no_editor_pane_exists(self) -> None:
        module = self.load_open_module(real_editor="hx")

        with (
            mock.patch.object(module, "run_stdout", side_effect=["@2\n", ""]),
            mock.patch.object(module, "activate_window_if_needed"),
            mock.patch.object(module.subprocess, "run") as run,
        ):
            self.assertEqual(module.open_in_tmux_editor([f"{self.real(REPO / 'README.md')}:4:2"]), 0)

        run.assert_called_once_with(
            [
                "tmux",
                "split-window",
                "-h",
                "-P",
                "-F",
                '"#{pane_id}"',
                "hx",
                f"{self.real(REPO / 'README.md')}:4:2",
            ],
            check=False,
            text=True,
            capture_output=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bin/open unit tests.")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each test name")
    args = parser.parse_args()

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OpenScriptTest)
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    return 0 if runner.run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
