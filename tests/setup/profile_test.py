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

        self.assertIn("mise_activation=$(mise activate bash) || return", profile)
        self.assertIn("mise_activation=$(mise activate zsh) || return", profile)
        self.assertIn('eval "$mise_activation" || return', profile)
        self.assertLess(
            profile.index("unset MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH"),
            profile.index("mise_activation=$(mise activate bash) || return"),
        )
        self.assertLess(
            profile.index('remove_path "$HOME/.local/share/mise/shims"'),
            profile.index("mise_activation=$(mise activate bash) || return"),
        )

    def test_mise_shims_are_added_after_linuxbrew(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertLess(
            profile.index("linuxbrew/.linuxbrew/bin/brew shellenv"),
            profile.index('. "$DOTFILES/lib/shell/paths.sh"'),
        )
        self.assertIn(
            "brew_env=$(/home/linuxbrew/.linuxbrew/bin/brew shellenv sh) || return",
            profile,
        )

    def test_noninteractive_profile_propagates_keychain_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binaries = root / "bin"
            home.mkdir()
            binaries.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            keychain = binaries / "keychain"
            keychain.write_text("#!/bin/sh\nexit 23\n")
            keychain.chmod(0o755)

            result = subprocess.run(
                ["/bin/sh", "-c", '. "$HOME/.profile"'],
                cwd=ROOT,
                env=os.environ
                | {
                    "HOME": str(home),
                    "PATH": f"{binaries}:{os.environ['PATH']}",
                    "SSH_AUTH_SOCK": "",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(23, result.returncode)

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

    def test_profile_does_not_fabricate_dotfiles_when_profile_resolution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binaries = root / "bin"
            home.mkdir()
            binaries.mkdir()
            realpath = binaries / "realpath"
            realpath.write_text(
                "#!/bin/sh\n"
                '[ "$1" = "$HOME/.profile" ] && exit 31\n'
                'exec /usr/bin/realpath "$@"\n'
            )
            realpath.chmod(0o755)
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$1"; profile_status=$?; '
                    'printf "%s:%s\\n" "$profile_status" "${DOTFILES-unset}"',
                    "sh",
                    str(ROOT / "config/profile"),
                ],
                cwd=ROOT,
                env=os.environ
                | {
                    "HOME": str(home),
                    "PATH": f"{binaries}:/usr/bin:/bin",
                    "SSH_AUTH_SOCK": "present",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("31:unset\n", result.stdout)

    def test_zsh_restores_native_emulation_after_profile_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".profile").write_text("return 23\n")
            result = subprocess.run(
                [
                    "zsh",
                    "-f",
                    "-c",
                    'unset DOTFILES; source "$1"; source_status=$?; '
                    'if [[ -o SH_WORD_SPLIT ]]; then mode=sh; else mode=zsh; fi; '
                    'printf "%s:%s\\n" "$source_status" "$mode"',
                    "zsh",
                    str(ROOT / "config/zshrc"),
                ],
                env=os.environ | {"HOME": str(home)},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("23:zsh\n", result.stdout)

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
        self.assertIn("pip_data=$(pip list --format=freeze) ||", profile)
        self.assertIn("packages=$(printf '%s\\n' \"$pip_data\" | sed", profile)
        self.assertNotIn("tail --lines=+3", profile)
        self.assertIn('$HOME/.config/helix/steel-lsp', languages)
        self.assertNotIn("/home/jyn", languages)
        self.assertEqual(2, profile.count('echo "no supported package manager found" >&2\n\t\treturn 1'))
        self.assertIn("printf 'remove crontab? [y/N] '", profile)
        self.assertIn('IFS= read -r reply || return', profile)
        self.assertNotIn("crontab -i -l", profile)
        self.assertIn('if [ -f "$file" ] && [ -x "$file" ]; then', profile)
        self.assertIn("recipes () (", profile)
        self.assertIn('recipies () { recipes "$@"; }', profile)

    def test_profile_checks_abbreviation_loading_before_defining_aliases(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertIn(
            "abbreviations=$(grep -Ev '^(#|$)' \"$DOTFILES/lib/abbr.txt\") || return",
            profile,
        )
        self.assertIn('eval "$snap_bin" || return', profile)
        self.assertIn('alias "$name"="$expn" || return', profile)
        for source in (
            '. "$DOTFILES/lib/shell/env.sh" || return',
            '. "$DOTFILES/lib/shell/paths.sh" || return',
            '. "$DOTFILES/lib/shell/lib.sh" || return',
            '. "$DOTFILES/bin/show-status" || return',
            '. "$DOTFILES/bin/prompt-command" || return',
        ):
            self.assertIn(source, profile)

    def test_git_merge_request_alias_quotes_dynamic_arguments(self) -> None:
        alias = subprocess.run(
            [
                "git",
                "config",
                "--no-includes",
                "-f",
                str(ROOT / "config/gitconfig"),
                "--get",
                "alias.mr",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout

        self.assertIn('git fetch "$1" "merge-requests/$2/head:mr-$2"', alias)
        self.assertIn('git checkout "mr-$2"', alias)

    def test_git_update_prompt_is_portable_and_declining_succeeds(self) -> None:
        alias = subprocess.run(
            [
                "git",
                "config",
                "--no-includes",
                "-f",
                str(ROOT / "config/gitconfig"),
                "--get",
                "alias.update",
            ],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.removeprefix("!")

        with tempfile.TemporaryDirectory() as directory:
            git = Path(directory) / "git"
            git.write_text("#!/bin/sh\nexit 0\n")
            git.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", "-c", alias],
                input="n\n",
                env=os.environ | {"PATH": f"{directory}:/usr/bin:/bin"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("push? [y/N] ", result.stdout)

    def test_git_new_creates_the_branch_without_detaching_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            repository.mkdir()
            subprocess.run(
                ["git", "init"], cwd=repository, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repository, check=True
            )
            (repository / "file").write_text("tea\n")
            subprocess.run(["git", "add", "file"], cwd=repository, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial"],
                cwd=repository,
                check=True,
                capture_output=True,
            )
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repository,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "remote", "add", "upstream", str(repository)],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "fetch", "upstream"],
                cwd=repository,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "symbolic-ref",
                    "refs/remotes/upstream/HEAD",
                    f"refs/remotes/upstream/{branch}",
                ],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "branch", "topic"], cwd=repository, check=True
            )
            config = f"include.path={ROOT / 'config/gitconfig'}"
            result = subprocess.run(
                ["/usr/bin/git", "-c", config, "new", "topic"],
                cwd=repository,
                text=True,
                capture_output=True,
                check=False,
            )
            current_branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repository,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(branch, current_branch)

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
        glide = (ROOT / "config/glide.ts").read_text()
        kakoune = (ROOT / "config/kakrc").read_text()
        profile = (ROOT / "config/profile").read_text()

        self.assertNotIn("; xargs open", tmux)
        self.assertGreaterEqual(tmux.count("xargs -0"), 2)
        self.assertIn("if (save != \\\"\\\")", tmux)
        self.assertIn('vim.fn.escape(comment, "\\\\/.*$^~[]")', nvim)
        self.assertIn('cmd = "git ls-files --modified"', nvim)
        self.assertNotIn(
            'cmd = "git ls-files --cached --others --exclude-standard"', nvim
        )
        self.assertIn("buffer = buf,\n\t\tcallback", nvim)
        for variable in ("selections", "swaps", "moves", "upper"):
            self.assertIn(f"local {variable} =", nvim)
        self.assertIn("function spaces(count, global)\n\tlocal opt", nvim)
        self.assertEqual(1, glide.count('glide.keymaps.set("normal", "U"'))
        self.assertIn('os === "mac" ? "<D-S-z>" : "<C-S-z>"', glide)
        self.assertEqual(2, glide.count("if (currentTab?.id == null) return;"))
        self.assertIn("if (next?.id == null) return;", glide)
        self.assertIn("if (tab?.id == null) return;", glide)
        self.assertIn("if (selection == null) return;", glide)
        for variable in ("paredit", "comment_api", "MiniStatusline"):
            self.assertIn(f"local {variable} =", nvim)
        self.assertIn('awk -v arg="$1"', profile)
        self.assertNotIn("arg=\"'\"$1\"'\"", profile)
        self.assertNotIn('rg "^$1"', profile)
        self.assertIn("base64 | tr -d '\\n'", kakoune)


if __name__ == "__main__":
    unittest.main()
