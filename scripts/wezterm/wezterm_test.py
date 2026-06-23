#!/usr/bin/env python3
"""Tests for wezterm.lua selector patterns."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
WEZTERM_CONFIG = REPO / "config" / "wezterm.lua"


def lua_single_quoted_string(name: str) -> str:
    text = WEZTERM_CONFIG.read_text(encoding="utf-8")
    match = re.search(rf"local {re.escape(name)} = '((?:\\.|[^'])*)'", text)
    if not match:
        raise AssertionError(f"could not find {name} in {WEZTERM_CONFIG}")
    value = match.group(1)
    return value.replace("\\\\", "\\")


def rg_matches(pattern: str, haystack: str, *, replace: str | None = None) -> list[str]:
    args = ["rg", "--no-filename", "--only-matching", "--regexp", pattern]
    if replace is not None:
        args.extend(["--replace", replace])
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=os.environ.get("TMPDIR"), delete=False
    ) as handle:
        handle.write(haystack)
        path = handle.name
    try:
        result = subprocess.run(
            [*args, path],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        Path(path).unlink(missing_ok=True)

    if result.returncode not in (0, 1):
        raise AssertionError(result.stderr)
    return result.stdout.splitlines()


class WeztermSelectorPatternTest(unittest.TestCase):
    def test_url_pattern_matches_full_remotes(self) -> None:
        pattern = lua_single_quoted_string("url_pattern")

        self.assertEqual(
            rg_matches(
                pattern,
                """\
github  https://github.com/jyn514/paracress (fetch)
github  git@github.com:jyn514/paracress (push)
v2      git@codeberg.org:jyn514/paracress.git (fetch)
v2      git@codeberg.org:jyn514/paracress.git (push)
""",
            ),
            [
                "https://github.com/jyn514/paracress",
                "git@github.com:jyn514/paracress",
                "git@codeberg.org:jyn514/paracress.git",
                "git@codeberg.org:jyn514/paracress.git",
            ],
        )

    def test_url_pattern_stops_before_closing_paren(self) -> None:
        pattern = lua_single_quoted_string("url_pattern")

        self.assertEqual(
            rg_matches(pattern, "remote (https://example.test/path?q=1)\n"),
            ["https://example.test/path?q=1"],
        )

    def test_path_pattern_matches_relative_absolute_and_line_suffixes(self) -> None:
        pattern = lua_single_quoted_string("path_pattern")

        self.assertEqual(
            rg_matches(
                pattern,
                """\
open config/wezterm.lua
edit ./config/tmux.conf:53
abs /Users/jyn/src/dotfiles/config/kitty.conf:6:1
home ~/.config/wezterm/wezterm.lua
""",
                replace="$1",
            ),
            [
                "config/wezterm.lua",
                "./config/tmux.conf:53",
                "/Users/jyn/src/dotfiles/config/kitty.conf:6:1",
                "~/.config/wezterm/wezterm.lua",
            ],
        )

    def test_path_pattern_does_not_match_git_remotes(self) -> None:
        pattern = lua_single_quoted_string("path_pattern")

        self.assertEqual(
            rg_matches(
                pattern,
                """\
github  git@github.com:jyn514/paracress (push)
v2      git@codeberg.org:jyn514/paracress.git (fetch)
""",
            ),
            [],
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
