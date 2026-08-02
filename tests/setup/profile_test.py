#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProfileContractTests(unittest.TestCase):
    def test_makeflags_has_an_explicit_parallelism_value(self) -> None:
        env = (ROOT / "lib/shell/env.sh").read_text()

        self.assertIn("export MAKEFLAGS='-j4'", env)
        self.assertNotIn("export MAKEFLAGS='-j'\n", env)

    def test_interactive_shells_activate_mise(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertIn('eval "$(mise activate bash)"', profile)
        self.assertIn('eval "$(mise activate zsh)"', profile)
        self.assertLess(
            profile.index("unset MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH"),
            profile.index('eval "$(mise activate bash)"'),
        )
        self.assertLess(
            profile.index('remove_path "$HOME/.local/share/mise/shims"'),
            profile.index('eval "$(mise activate bash)"'),
        )

    def test_mise_shims_are_added_after_linuxbrew(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertLess(
            profile.index("linuxbrew/.linuxbrew/bin/brew shellenv"),
            profile.index('. "$DOTFILES/lib/shell/paths.sh"'),
        )

    def test_noninteractive_profile_exposes_tool_and_dotfile_paths_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            cargo_bin = home / ".local/lib/cargo/bin"
            local_bin = home / ".local/bin"
            mise_shims = home / ".local/share/mise/shims"
            cargo_bin.mkdir(parents=True)
            local_bin.mkdir(parents=True)
            mise_shims.mkdir(parents=True)
            env = os.environ.copy()
            env.update(
                HOME=str(home),
                PATH=f"{local_bin}:/usr/bin:{local_bin}",
                SSH_AUTH_SOCK="",
            )

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$HOME/.profile"; printf "%s\\n" "$PATH"',
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            paths = result.stdout.strip().split(":")
            expected_prefix = [
                str(mise_shims),
                str(ROOT / "bin"),
                str(local_bin),
                str(cargo_bin),
            ]
            self.assertEqual(expected_prefix, paths[: len(expected_prefix)])
            self.assertEqual(1, paths.count(str(local_bin)))
            self.assertEqual(1, paths.count(str(cargo_bin)))
            self.assertEqual(1, paths.count(str(mise_shims)))

    def test_path_helpers_do_not_expand_glob_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            home = directory / "home"
            home.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            (directory / "literal-a").touch()
            env = os.environ.copy()
            env.update(HOME=str(home), SSH_AUTH_SOCK="")

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$HOME/.profile"; cd "$1" || exit; '
                    "PATH='literal-*:/bin'; add_path /new; remove_path /missing; "
                    'printf "%s\\n" "$PATH"',
                    "sh",
                    str(directory),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("/new:literal-*:/bin\n", result.stdout)

    def test_portable_profile_and_cross_platform_config_paths(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        languages = (ROOT / "config/helix/languages.toml").read_text()

        self.assertIn("pip list --format=freeze", profile)
        self.assertNotIn("tail --lines=+3", profile)
        self.assertIn('$HOME/.config/helix/steel-lsp', languages)
        self.assertNotIn("/home/jyn", languages)

    def test_codeberg_push_url_rewrite_removes_the_https_slash(self) -> None:
        result = subprocess.run(
            [
                "git",
                "config",
                "-f",
                str(ROOT / "config/gitconfig"),
                "--get",
                "url.git@codeberg.org:.pushinsteadof",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("https://codeberg.org/\n", result.stdout)

    def test_path_consumers_and_comment_regex_preserve_literal_text(self) -> None:
        tmux = (ROOT / "config/tmux.conf").read_text()
        nvim = (ROOT / "config/nvim.lua").read_text()

        self.assertNotIn("; xargs open", tmux)
        self.assertGreaterEqual(tmux.count("xargs -0"), 2)
        self.assertIn('vim.fn.escape(comment, "\\\\/.*$^~[]")', nvim)


if __name__ == "__main__":
    unittest.main()
