#!/usr/bin/env python3
"""Behavioral tests for tmux's file-path search expression."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGEX_SCRIPT = ROOT / "lib" / "shell" / "search-regex.sh"
TMUX_CONFIG = ROOT / "config" / "tmux.conf"


@unittest.skipUnless(shutil.which("tmux"), "tmux is required")
class SearchRegexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = subprocess.run(
            ["sh", str(REGEX_SCRIPT)],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.regex = result.stdout.rstrip("\n")

    def tmux_match(self, text: str) -> str | None:
        socket = f"search-regex-test-{os.getpid()}-{uuid.uuid4().hex}"
        environment = os.environ | {"SEARCH_REGEX_INPUT": text}

        def tmux(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["tmux", "-L", socket, *arguments],
                check=check,
                capture_output=True,
                text=True,
                timeout=10,
                env=environment,
            )

        try:
            tmux(
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-x",
                "160",
                "-y",
                "5",
                "sh",
                "-c",
                'printf "%s\\n" "$SEARCH_REGEX_INPUT"; '
                "tmux wait-for -S search-regex-ready; sleep 30",
            )
            tmux("wait-for", "search-regex-ready")
            tmux("copy-mode")
            tmux("send-keys", "-X", "history-top")
            tmux("send-keys", "-X", "search-forward", self.regex)
            search_present = tmux(
                "display-message", "-p", "#{search_present}"
            ).stdout.strip()
            if search_present != "1":
                return None

            tmux("send-keys", "-X", "copy-selection-and-cancel")
            saved = tmux("save-buffer", "-", check=False)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            return saved.stdout
        finally:
            tmux("kill-server", check=False)

    def test_generated_regex_matches_tmux_configuration(self) -> None:
        expected = f"send-keys -X search-backward '{self.regex}'"
        self.assertIn(expected, TMUX_CONFIG.read_text())

    def test_matches_paths_using_tmux_regex_engine(self) -> None:
        cases = {
            "Error in /usr/local/etc/filename.txt at line 42": "/usr/local/etc/filename.txt",
            "Check foo/something.conf for settings": "foo/something.conf",
            "See ./foo.txt for details": "./foo.txt",
            "bin/foo:12 contains the error": "bin/foo:12",
            "src/main.rs:12:3: error": "src/main.rs:12:3",
            "Navigate to foo/bar/baz directory": "foo/bar/baz",
            "foo/bar/baz/": "foo/bar/baz/",
            "10:59:58 ~/jyn/dotfiles main": "~/jyn/dotfiles",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                match = self.tmux_match(text)
                self.assertIsNotNone(match)
                self.assertIn(expected, match)

    def test_rejects_non_paths_using_tmux_regex_engine(self) -> None:
        for text in (
            "Variable x.y.z is undefined",
            "Simple word foo without context",
            "x.y.z:12",
            "something.conf",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.tmux_match(text))

    def test_rejects_git_remote_branch(self) -> None:
        self.assertIsNone(self.tmux_match("origin/main"))

    def test_matches_bare_filename_with_line_number(self) -> None:
        self.assertEqual(
            self.tmux_match("copycat.tmux:43:    tmux list-keys"),
            "copycat.tmux:43:",
        )

    def test_keeps_leading_dot_in_hidden_path(self) -> None:
        self.assertEqual(
            self.tmux_match(".github/workflows/ci.yml:10"),
            ".github/workflows/ci.yml:10",
        )

    def test_does_not_match_url_as_a_path(self) -> None:
        self.assertIsNone(self.tmux_match("https://example.com/a/b"))

    def test_path_is_separable_from_consumed_context_delimiters(self) -> None:
        match = self.tmux_match("Running bin/foo without path")

        self.assertIsNotNone(match)
        self.assertEqual(match.strip(" \t\""), "bin/foo")


if __name__ == "__main__":
    unittest.main()
