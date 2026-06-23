#!/usr/bin/env python3
"""Characterization tests for bin/open.

These tests drive the current implementation as an external process. They put
small fake commands at the front of PATH and assert the observable process I/O.
The same harness can later run against a Python port by setting OPEN_UNDER_TEST.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote


REPO = Path(__file__).resolve().parents[2]
DEFAULT_OPEN = REPO / "bin" / "open"
DEFAULT_HX_HAX = REPO / "bin" / "hx-hax"


FAKE_COMMAND = """\
#!{python}
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
argv = sys.argv[1:]

with open(os.environ["OPEN_TEST_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"cmd": name, "argv": argv}}) + "\\n")

if name == "bash":
    print(os.environ["OPEN_TEST_PATH"])
    raise SystemExit(0)

responses = json.loads(os.environ.get("OPEN_TEST_RESPONSES", "{{}}"))
for rule in responses.get(name, []):
    contains = rule.get("contains", [])
    joined = "\\0".join(argv)
    if all(needle in joined for needle in contains):
        sys.stdout.write(rule.get("stdout", ""))
        sys.stderr.write(rule.get("stderr", ""))
        raise SystemExit(rule.get("exit", 0))

raise SystemExit(0)
"""


class FakeCommands:
    def __init__(self, case: unittest.TestCase):
        self.case = case
        self.tmp = tempfile.TemporaryDirectory(
            prefix="open-test-", dir=os.environ.get("TMPDIR")
        )
        self.root = Path(self.tmp.name)
        self.bin = self.root / "fakebin"
        self.bin.mkdir()
        self.log = self.root / "calls.jsonl"
        self.responses: dict[str, list[dict[str, object]]] = {}

    def cleanup(self) -> None:
        self.tmp.cleanup()

    def add(self, name: str, responses: list[dict[str, object]] | None = None) -> None:
        script = self.bin / name
        script.write_text(FAKE_COMMAND.format(python=sys.executable), encoding="utf-8")
        script.chmod(0o755)
        if responses is not None:
            self.responses[name] = responses

    def env(
        self,
        extra: dict[str, str] | None = None,
        *,
        inherit_path: bool = True,
    ) -> dict[str, str]:
        original_path = os.environ.get("PATH", "")
        if inherit_path:
            path = f"{self.bin}{os.pathsep}{original_path}"
        else:
            path = f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.root / "home"),
                "OPEN_TEST_LOG": str(self.log),
                "OPEN_TEST_PATH": path,
                "OPEN_TEST_RESPONSES": json.dumps(self.responses),
                "PATH": path,
            }
        )
        if extra:
            env.update(extra)
        return env

    def calls(self, name: str | None = None) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if name is None:
            return calls
        return [call for call in calls if call["cmd"] == name]


class OpenScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fakes = FakeCommands(self)
        self.addCleanup(self.fakes.cleanup)
        self.open_under_test = Path(os.environ.get("OPEN_UNDER_TEST", DEFAULT_OPEN))

    def run_open(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        argv0: Path | None = None,
        inherit_path: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        target = argv0 or self.open_under_test
        return subprocess.run(
            [str(target), *args],
            cwd=REPO,
            env=self.fakes.env(env, inherit_path=inherit_path),
            text=True,
            capture_output=True,
            check=False,
        )

    @staticmethod
    def real(path: Path) -> str:
        return str(path.resolve())

    def test_plain_url_uses_xdg_open(self) -> None:
        self.fakes.add("bash")
        self.fakes.add("xdg-open")

        result = self.run_open(["https://example.test/path:12"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": ["https://example.test/path:12"]}],
        )

    def test_missing_args_prints_literal_usage_and_fails(self) -> None:
        self.fakes.add("bash")

        result = self.run_open([])

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_plain_file_without_line_uses_xdg_open(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")

        result = self.run_open([str(target)])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [str(target)]}],
        )

    def test_plain_multiple_args_are_forwarded_to_xdg_open(self) -> None:
        first = self.fakes.root / "first.txt"
        second = self.fakes.root / "second.txt"
        first.write_text("tea\n", encoding="utf-8")
        second.write_text("water\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")

        result = self.run_open(["--reveal", str(first), str(second)])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": ["--reveal", str(first), str(second)]}],
        )

    def test_tilde_is_expanded_before_os_open(self) -> None:
        home = self.fakes.root / "home"
        target = home / "note.txt"
        target.parent.mkdir()
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")

        result = self.run_open(["~/note.txt"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [str(target)]}],
        )

    def test_non_editor_default_opens_file_without_line_suffix(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "org.example.Viewer.desktop\n"}])

        result = self.run_open([f"{target}:7"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [self.real(target)]}],
        )

    def test_real_editor_nvim_matches_unset_editor_behavior(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "nvim.desktop\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:10"], env={"REAL_EDITOR": "nvim"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["send-keys", "-t", "%4", f": drop +normal!10G| {self.real(target)}", "Enter"],
            tmux_argv,
        )

    def test_real_editor_as_absolute_path_uses_path_as_command_and_desktop_regex(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        editor = self.fakes.root / "editors" / "nvim"
        editor.parent.mkdir()
        editor.write_text(
            "#!/bin/sh\n"
            'printf \'{"cmd":"abs-nvim","argv":['
            ' >> "$OPEN_TEST_LOG"\n',
            encoding="utf-8",
        )
        editor.chmod(0o755)
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": str(editor) + ".desktop\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:10"], env={"REAL_EDITOR": str(editor)})

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["send-keys", "-t", "%4", f": open {self.real(target)}:10", "Enter"],
            tmux_argv,
        )

    def test_editor_name_regex_metacharacters_do_not_match_unrelated_default(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("a.n")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "axon.desktop\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:10"], env={"REAL_EDITOR": "a.n"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [self.real(target)]}],
        )

    def test_dash_leading_filename_with_line_is_passed_to_editor(self) -> None:
        target = self.fakes.root / "-note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:3"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!3G|", self.real(target)]}],
        )

    def test_directory_path_with_line_is_canonicalized(self) -> None:
        target = self.fakes.root / "notes"
        target.mkdir()
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:3"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!3G|", self.real(target)]}],
        )

    def test_symlink_path_with_line_is_resolved(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        link_target = self.fakes.root / "link.txt"
        link_target.symlink_to(target)
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{link_target}:3"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!3G|", self.real(target)]}],
        )

    def test_relative_nonexistent_file_with_line_becomes_absolute(self) -> None:
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open(["missing-relative.txt:3"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!3G|", str(REPO / "missing-relative.txt")]}],
        )

    def test_file_url_localhost_with_line_uses_uri_path(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"file://localhost{target}:3"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!3G|", self.real(target)]}],
        )

    def test_multi_dot_extension_uses_last_extension_for_duti(self) -> None:
        target = self.fakes.root / "archive.tar.gz"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "gz"], "stdout": "org.example.Archive.desktop\n"}])

        result = self.run_open([f"{target}:4"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("duti"),
            [{"cmd": "duti", "argv": ["-x", "gz"]}],
        )
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [self.real(target)]}],
        )

    def test_non_editor_default_with_multiple_args_drops_preceding_args(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "org.example.Viewer.desktop\n"}])

        result = self.run_open(["--first", "--second", f"{target}:7"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [self.real(target)]}],
        )

    def test_existing_filename_ending_colon_digits_is_split_anyway(self) -> None:
        target = self.fakes.root / "note:7"
        target.write_text("tea\n", encoding="utf-8")
        split_target = self.fakes.root / "note"
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "note"], "stdout": "org.example.Viewer.desktop\n"}])

        result = self.run_open([str(target)])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [self.real(split_target)]}],
        )

    def test_nonexistent_file_with_line_keeps_uncanonicalized_path(self) -> None:
        target = self.fakes.root / "missing.txt"
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "nvim.desktop\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:12"])

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["send-keys", "-t", "%4", f": drop +normal!12G| {self.real(target)}", "Enter"],
            tmux_argv,
        )

    def test_file_url_without_line_uses_os_open(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")

        result = self.run_open([f"file://{target}"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [f"file://{target}"]}],
        )

    def test_file_url_with_escaped_space_and_line_through_open_is_not_split(self) -> None:
        target = self.fakes.root / "space name.txt"
        target.write_text("tea\n", encoding="utf-8")
        escaped = quote(str(target), safe="/")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "org.example.Viewer.desktop\n"}])

        result = self.run_open([f"file://{escaped}:5"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [f"file://{escaped}:5"]}],
        )

    def test_uppercase_url_scheme_is_not_split_as_line_number(self) -> None:
        self.fakes.add("bash")
        self.fakes.add("xdg-open")

        result = self.run_open(["HTTPS://example.test/path:12"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": ["HTTPS://example.test/path:12"]}],
        )

    def test_uppercase_file_url_scheme_through_editor_hax_is_decoded(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"FILE://{target}:5"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!5G|", self.real(target)]}],
        )

    def test_xdg_mime_failure_falls_back_to_os_open(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add(
            "xdg-mime",
            [{"contains": ["query", "filetype"], "stderr": "no mime\n", "exit": 1}],
        )

        result = self.run_open([f"{target}:8"], inherit_path=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("xdg-open"),
            [{"cmd": "xdg-open", "argv": [self.real(target)]}],
        )

    def test_xdg_mime_default_is_used_when_duti_and_gio_are_absent(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add(
            "xdg-mime",
            [
                {"contains": ["query", "filetype"], "stdout": "text/plain\n"},
                {"contains": ["query", "default"], "stdout": "nvim.desktop\n"},
            ],
        )
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:8"], inherit_path=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["send-keys", "-t", "%4", f": drop +normal!8G| {self.real(target)}", "Enter"],
            tmux_argv,
        )

    def test_gio_default_is_used_when_duti_is_absent(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add(
            "xdg-mime",
            [{"contains": ["query", "filetype"], "stdout": "text/plain\n"}],
        )
        self.fakes.add(
            "gio",
            [{"contains": ["mime", "text/plain"], "stdout": "Default application for text/plain: nvim.desktop\n"}],
        )
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:8"], inherit_path=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["send-keys", "-t", "%4", f": drop +normal!8G| {self.real(target)}", "Enter"],
            tmux_argv,
        )

    def test_macos_open_fallback_removes_script_directory_from_path(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        bin_dir = self.fakes.root / "scriptbin"
        bin_dir.mkdir()
        link = bin_dir / "open"
        link.symlink_to(DEFAULT_HX_HAX)
        self.fakes.add("bash")
        self.fakes.add("open")

        env = self.fakes.env()
        env["OPEN_TEST_PATH"] = f"{bin_dir}{os.pathsep}{env['OPEN_TEST_PATH']}"
        env["PATH"] = env["OPEN_TEST_PATH"]
        result = subprocess.run(
            [str(link), str(target)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("open"),
            [{"cmd": "open", "argv": [str(target)]}],
        )

    def test_editor_default_sends_nvim_position_to_tmux(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "nvim.desktop\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:7:3"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(["send-keys", "-t", "%4", "-X", "cancel"], tmux_argv)
        self.assertIn(
            [
                "send-keys",
                "-t",
                "%4",
                ": drop +normal!7G3| "
                + self.real(target),
                "Enter",
            ],
            tmux_argv,
        )

    def test_editor_default_matches_bare_editor_name(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "nvim\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:7"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])

    def test_hx_default_matches_helix_desktop(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "Helix.desktop\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:7"], env={"REAL_EDITOR": "hx"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["send-keys", "-t", "%4", f": open {self.real(target)}:7", "Enter"],
            tmux_argv,
        )

    def test_textedit_default_is_treated_as_editor_like(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("xdg-open")
        self.fakes.add("duti", [{"contains": ["-x", "txt"], "stdout": "TextEdit\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([f"{target}:7"])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fakes.calls("xdg-open"), [])

    def test_trailing_colon_is_included_in_nvim_normal_command(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:6:"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!6G:|", self.real(target)]}],
        )

    def test_editor_hax_without_line_execs_editor_with_file_only(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([str(target)], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": [self.real(target)]}],
        )

    def test_editor_hax_preserves_shell_sensitive_filename_characters(self) -> None:
        target = self.fakes.root / "semi;pipe|quote'.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:4"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [{"cmd": "nvim", "argv": ["+normal!4G|", self.real(target)]}],
        )

    def test_file_url_with_position_is_decoded_for_editor(self) -> None:
        target = self.fakes.root / "space name.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("nvim")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"file://{target}:11:2"], argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("nvim"),
            [
                {
                    "cmd": "nvim",
                    "argv": ["+normal!11G2|", quote(self.real(target), safe="/")],
                }
            ],
        )

    def test_kak_editor_position_argument_order(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("kak")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:9:5"], env={"REAL_EDITOR": "kak"}, argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("kak"),
            [{"cmd": "kak", "argv": [self.real(target), "+9:5"]}],
        )

    def test_kak_editor_line_only_argument_order(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("kak")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:9"], env={"REAL_EDITOR": "kak"}, argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("kak"),
            [{"cmd": "kak", "argv": [self.real(target), "+9"]}],
        )

    def test_non_special_editor_gets_file_line_column_joined(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("micro")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:9:5"], env={"REAL_EDITOR": "micro"}, argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("micro"),
            [{"cmd": "micro", "argv": [f"{self.real(target)}:9:5"]}],
        )

    def test_non_special_editor_line_only_gets_file_line_joined(self) -> None:
        target = self.fakes.root / "note.txt"
        target.write_text("tea\n", encoding="utf-8")
        self.fakes.add("bash")
        self.fakes.add("micro")

        link = self.fakes.root / "editor-hax"
        link.symlink_to(DEFAULT_HX_HAX)

        result = self.run_open([f"{target}:9"], env={"REAL_EDITOR": "micro"}, argv0=link)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.fakes.calls("micro"),
            [{"cmd": "micro", "argv": [f"{self.real(target)}:9"]}],
        )

    def test_hx_hax_reuses_existing_tmux_pane(self) -> None:
        self.fakes.add("bash")
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open(["README.md:3"], env={"REAL_EDITOR": "hx"}, argv0=DEFAULT_HX_HAX)

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(["send-keys", "-t", "%4", "-X", "cancel"], tmux_argv)
        self.assertIn(
            ["send-keys", "-t", "%4", f": open {self.real(REPO / 'README.md')}:3", "Enter"],
            tmux_argv,
        )
        self.assertIn(["select-pane", "-t", "%4", "-Z"], tmux_argv)

    def test_hx_hax_with_no_args_sends_empty_open_command(self) -> None:
        self.fakes.add("bash")
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open([], env={"REAL_EDITOR": "hx"}, argv0=DEFAULT_HX_HAX)

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(["send-keys", "-t", "%4", ": open ", "Enter"], tmux_argv)

    def test_hx_hax_whitespace_pane_output_counts_as_existing_empty_pane(self) -> None:
        self.fakes.add("bash")
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "   \n"},
                {"contains": ["split-window"], "stdout": "%9\n"},
            ],
        )

        result = self.run_open(["README.md:4"], env={"REAL_EDITOR": "hx"}, argv0=DEFAULT_HX_HAX)

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertNotIn("split-window", [argv[0] for argv in tmux_argv])
        self.assertIn(["send-keys", "-t", "-X", "cancel"], tmux_argv)

    def test_hx_hax_activates_window_with_xdotool_when_display_is_set(self) -> None:
        self.fakes.add("bash")
        self.fakes.add("xdotool", [{"contains": ["getwindowpid"], "stdout": "123\n"}])
        self.fakes.add("pstree", [{"contains": ["123"], "stdout": "i3---zsh\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open(
            ["README.md:3"],
            env={"DISPLAY": ":1", "WINDOWID": "777", "REAL_EDITOR": "hx"},
            argv0=DEFAULT_HX_HAX,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            ["run-shell", "-t", "%4", "xdotool", "windowactivate", "777"],
            tmux_argv,
        )

    def test_hx_hax_does_not_activate_window_when_active_window_is_tmux(self) -> None:
        self.fakes.add("bash")
        self.fakes.add("xdotool", [{"contains": ["getwindowpid"], "stdout": "123\n"}])
        self.fakes.add("pstree", [{"contains": ["123"], "stdout": "i3---tmux---zsh\n"}])
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open(
            ["README.md:3"],
            env={"DISPLAY": ":1", "WINDOWID": "777", "REAL_EDITOR": "hx"},
            argv0=DEFAULT_HX_HAX,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertNotIn(
            ["run-shell", "-t", "%4", "xdotool", "windowactivate", "777"],
            tmux_argv,
        )

    @unittest.skipUnless(sys.platform == "darwin", "Darwin-only osascript branch")
    def test_hx_hax_on_darwin_activates_iterm_with_osascript(self) -> None:
        self.fakes.add("bash")
        self.fakes.add("osascript")
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": "%4\n"},
            ],
        )

        result = self.run_open(
            ["README.md:3"],
            env={"REAL_EDITOR": "hx", "DISPLAY": ""},
            argv0=DEFAULT_HX_HAX,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.fakes.calls("osascript")), 1)

    def test_hx_hax_creates_tmux_pane_when_no_editor_pane_exists(self) -> None:
        self.fakes.add("bash")
        self.fakes.add(
            "tmux",
            [
                {"contains": ["display-message"], "stdout": "@2\n"},
                {"contains": ["list-panes"], "stdout": ""},
                {"contains": ["split-window"], "stdout": "%9\n"},
            ],
        )

        result = self.run_open(["README.md:4:2"], env={"REAL_EDITOR": "hx"}, argv0=DEFAULT_HX_HAX)

        self.assertEqual(result.returncode, 0, result.stderr)
        tmux_argv = [call["argv"] for call in self.fakes.calls("tmux")]
        self.assertIn(
            [
                "split-window",
                "-h",
                "-P",
                "-F",
                '"#{pane_id}"',
                "hx",
                f"{self.real(REPO / 'README.md')}:4:2",
            ],
            tmux_argv,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
