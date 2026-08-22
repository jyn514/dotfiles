#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProfileContractTests(unittest.TestCase):
    @unittest.skipUnless(Path("/bin/zsh").exists(), "zsh is unavailable")
    def test_zshenv_selects_tracked_login_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            zsh_config = home / ".config/zsh"
            zsh_config.mkdir(parents=True)
            (home / ".zshenv").symlink_to(ROOT / "config/zshenv")
            (zsh_config / ".zprofile").write_text("export PROFILE_READ=yes\n")

            for environment in (
                {"HOME": str(home), "PATH": "/usr/bin:/bin"},
                {
                    "HOME": str(home),
                    "PATH": "/usr/bin:/bin",
                    "ZDOTDIR": str(zsh_config),
                },
            ):
                result = subprocess.run(
                    ["/bin/zsh", "-l", "-c", 'printf "%s:%s\\n" "$PROFILE_READ" "$ZDOTDIR"'],
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(f"yes:{zsh_config}\n", result.stdout)

    def test_makeflags_has_an_explicit_parallelism_value(self) -> None:
        env = (ROOT / "lib/shell/env.sh").read_text()

        self.assertIn("export MAKEFLAGS='-j4'", env)
        self.assertNotIn("export MAKEFLAGS='-j'\n", env)

    def test_interactive_shells_activate_mise(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertIn("mise_activation=$(mise activate bash) || {", profile)
        self.assertIn("mise_activation=$(mise activate zsh) || {", profile)
        self.assertIn('eval "$mise_activation" || {', profile)
        self.assertLess(
            profile.index("unset MISE_SHELL __MISE_DIFF __MISE_SESSION __MISE_ORIG_PATH"),
            profile.index("mise_activation=$(mise activate bash) || {"),
        )
        self.assertLess(
            profile.index('remove_path "$HOME/.local/share/mise/shims"'),
            profile.index("mise_activation=$(mise activate bash) || {"),
        )
        self.assertGreater(
            profile.index('add_path "$DOTFILES/bin"', profile.index("if exists mise; then")),
            profile.index('eval "$mise_activation" || {'),
        )
        self.assertLess(
            profile.index('add_path "$DOTFILES/bin"'),
            profile.index('case "$-" in'),
        )

        fish = (ROOT / "config/config.fish").read_text()
        self.assertIn("source_init mise hook-env --shell fish --force", fish)
        self.assertNotIn("add_path $DOTFILES/libexec/agent-wrappers", fish)
        self.assertLess(
            fish.index("source_init mise hook-env --shell fish --force"),
            fish.index("if not status --is-interactive"),
        )

    def test_mise_shims_are_added_after_linuxbrew(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertLess(
            profile.index("linuxbrew/.linuxbrew/bin/brew shellenv"),
            profile.index('. "$DOTFILES/lib/shell/paths.sh"'),
        )
        self.assertIn(
            "brew_env=$(/home/linuxbrew/.linuxbrew/bin/brew shellenv sh) || {",
            profile,
        )

    def test_path_helpers_preserve_caller_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    "p=caller-p; existing=caller-existing; new_path=caller-new; "
                    "old_ifs=caller-ifs; restore_glob=caller-glob; "
                    '. "$HOME/.profile"; add_path /added; remove_path /added; '
                    "printf '%s|%s|%s|%s|%s\\n' \"$p\" \"$existing\" "
                    '"$new_path" "$old_ifs" "$restore_glob"',
                ],
                cwd=ROOT,
                env=os.environ
                | {
                    "HOME": str(home),
                    "PATH": "/usr/bin:/bin",
                    "SSH_AUTH_SOCK": "present",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "caller-p|caller-existing|caller-new|caller-ifs|caller-glob\n",
            result.stdout,
        )

    def test_bash_startup_cleans_failed_initializer_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binaries = Path(directory)
            zoxide = binaries / "zoxide"
            zoxide.write_text("#!/bin/sh\nprintf 'partial output\\n'\nexit 42\n")
            zoxide.chmod(0o755)
            result = subprocess.run(
                [
                    "/bin/bash",
                    "--noprofile",
                    "--norc",
                    "-ic",
                    'exists() { [ "$1" = zoxide ]; }; MY_GITHUB=1; '
                    'source "$1"; startup_status=$?; '
                    'printf "%s:%s\\n" "$startup_status" "${zoxide_init-unset}"',
                    "bash",
                    str(ROOT / "config/bashrc"),
                ],
                env=os.environ
                | {"PATH": f"{binaries}:/usr/bin:/bin", "TERM": "dumb"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("42:unset\n", result.stdout)

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

    def test_noninteractive_profile_propagates_hostname_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binaries = root / "bin"
            home.mkdir()
            binaries.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            keychain = binaries / "keychain"
            keychain.write_text("#!/bin/sh\nprintf ':\\n'\n")
            keychain.chmod(0o755)
            hostname = binaries / "hostname"
            hostname.write_text("#!/bin/sh\nexit 29\n")
            hostname.chmod(0o755)

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

        self.assertEqual(29, result.returncode)

    def test_profile_rejects_partial_snap_path_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binaries = root / "bin"
            home.mkdir()
            binaries.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            snap = binaries / "snap"
            snap.write_text("#!/bin/sh\nprintf 'SNAPD_BIN=/partial\\n'\nexit 23\n")
            snap.chmod(0o755)

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$HOME/.profile"; status=$?; '
                    'printf "%s:%s\\n" "$status" "${SNAPD_BIN-unset}"',
                ],
                cwd=ROOT,
                env=os.environ
                | {
                    "HOME": str(home),
                    "PATH": f"{binaries}:{os.environ['PATH']}",
                    "SSH_AUTH_SOCK": "present",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("23:unset\n", result.stdout)

    def test_profile_adds_a_successful_snap_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binaries = root / "bin"
            home.mkdir()
            binaries.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            snap = binaries / "snap"
            snap.write_text("#!/bin/sh\nprintf 'SNAPD_BIN=/snap/bin\\n'\n")
            snap.chmod(0o755)

            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    '. "$HOME/.profile"; printf "%s:%s\\n" "$SNAPD_BIN" "$PATH"',
                ],
                cwd=ROOT,
                env=os.environ
                | {
                    "HOME": str(home),
                    "PATH": f"{binaries}:{os.environ['PATH']}",
                    "SSH_AUTH_SOCK": "present",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        snap_bin, path = result.stdout.rstrip().split(":", 1)
        self.assertEqual("/snap/bin", snap_bin)
        self.assertIn("/snap/bin", path.split(":"))

    def test_tmux_paste_bindings_do_not_paste_after_clipboard_failure(self) -> None:
        tmux_config = (ROOT / "config/tmux.conf").read_text()
        commands = re.findall(
            r"bash -o pipefail -c '([^']*paste(?: --primary)? \| tmux load-buffer[^']*)'",
            tmux_config,
        )
        self.assertEqual(4, len(commands))

        with tempfile.TemporaryDirectory() as directory:
            binaries = Path(directory)
            paste = binaries / "paste"
            paste.write_text("#!/bin/sh\nexit 31\n")
            paste.chmod(0o755)
            tmux = binaries / "tmux"
            tmux.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$TMUX_CALLS\"\n")
            tmux.chmod(0o755)
            calls = binaries / "calls"
            env = os.environ | {
                "PATH": f"{binaries}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            }

            for command in commands:
                result = subprocess.run(
                    ["/bin/bash", "-o", "pipefail", "-c", command],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(31, result.returncode, command)

            tmux_calls = calls.read_text()
            self.assertIn("load-buffer", tmux_calls)
            self.assertNotIn("paste-buffer", tmux_calls)

    def test_tmux_copy_actions_pass_hostile_text_as_one_argument(self) -> None:
        tmux_config = (ROOT / "config/tmux.conf").read_text()
        dragon_commands = re.findall(
            r"'cd #\{q:pane_current_path\}; ([^']*~/\.config/tmux/dragon\.sh --read0)'",
            tmux_config,
        )
        self.assertEqual(2, len(dragon_commands))
        self.assertEqual(5, tmux_config.count("~/.config/tmux/dragon.sh"))
        self.assertNotIn("xargs -0 ~/.config/tmux/dragon.sh", tmux_config)
        search_command = re.search(
            r"'cd #\{q:pane_current_path\}; ([^']*~/\.config/tmux/picker-action search --read0)'",
            tmux_config,
        )
        open_command = re.search(
            r"'cd #\{q:pane_current_path\}; ([^']*~/\.config/tmux/picker-action open --read0)'",
            tmux_config,
        )
        edit_command = re.search(
            r"'cd #\{q:pane_current_path\}; ([^']*~/\.config/tmux/picker-action edit --read0)'",
            tmux_config,
        )
        self.assertIsNotNone(search_command)
        self.assertIsNotNone(open_command)
        self.assertIsNotNone(edit_command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            calls = root / "calls"
            marker = root / "injected"
            payload = f"odd ' $(touch {marker})\nname"
            for name in ("dragon", "open", "tmux"):
                executable = binaries / name
                executable.write_text(
                    '#!/bin/sh\nprintf "%s" "$*" > "$ACTION_CALLS"\n'
                )
                executable.chmod(0o755)
            env = os.environ | {
                "ACTION_CALLS": str(calls),
                "PATH": f"{binaries}:{os.environ['PATH']}",
            }

            for command in dragon_commands:
                command = command.replace(
                    "~/.config/tmux/dragon.sh", str(ROOT / "config/dragon.sh")
                )
                result = subprocess.run(
                    ["/bin/bash", "-c", command],
                    input=payload,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(f"-x {payload}", calls.read_text())

            command = open_command.group(1).replace(
                "~/.config/tmux/picker-action", str(ROOT / "bin/picker-action")
            )
            result = subprocess.run(
                ["/bin/bash", "-c", command],
                input=payload,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(payload, calls.read_text())

            command = edit_command.group(1).replace(
                "~/.config/tmux/picker-action", str(ROOT / "bin/picker-action")
            )
            result = subprocess.run(
                ["/bin/bash", "-c", command],
                input=payload,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(marker.exists())

            command = search_command.group(1).replace(
                "~/.config/tmux/picker-action", str(ROOT / "bin/picker-action")
            )
            result = subprocess.run(
                ["/bin/bash", "-c", command],
                input=payload,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                "https://www.google.com/search?"
                "q=odd+%27+%24%28touch+"
                f"{str(marker).replace('/', '%2F')}%29%0Aname",
                calls.read_text(),
            )
            self.assertFalse(marker.exists())

    def test_zsh_sudo_uses_the_current_buffer_when_present(self) -> None:
        zshrc = (ROOT / "config/zshrc").read_text()
        function = re.search(r"zle-sudo\(\) \{(.*?)\n\}", zshrc, re.DOTALL)
        self.assertIsNotNone(function)
        body = function.group(1)
        self.assertIn("if [[ -z $BUFFER ]]", body)
        self.assertIn("zle up-line-or-history", body)
        self.assertIn('LBUFFER="sudo $LBUFFER"', body)

    def test_neovim_tab_alignment_and_alternate_buffer_use_editor_columns(self) -> None:
        nvim = (ROOT / "config/nvim.lua").read_text()

        self.assertIn("local byte_col = vim.fn.getcurpos()[3] - 1", nvim)
        self.assertIn("local display_col = vim.fn.virtcol('.') - 1", nvim)
        self.assertIn("vim.fn.getline('.'):sub(1, byte_col)", nvim)
        self.assertIn("local width = sw - (display_col % sw)", nvim)
        self.assertNotIn("sw - ((col - 1) % sw)", nvim)
        self.assertIn("vim.cmd.balt(vim.fn.fnameescape(name))", nvim)
        self.assertNotIn("let @#", nvim)

    def test_dynamic_shell_and_editor_values_are_computed_when_used(self) -> None:
        fish_z = (ROOT / "config/z.fish").read_text()
        nvim = (ROOT / "config/nvim.lua").read_text()

        self.assertTrue(fish_z.startswith("function __z_arguments\n"))
        self.assertIn(
            "function __z_arguments\n\tset -l curr_tok (builtin commandline",
            fish_z,
        )
        command = re.search(
            r"nvim_create_user_command\('EditDailyJournal', function\(\)(.*?)end,",
            nvim,
            re.DOTALL,
        )
        self.assertIsNotNone(command)
        self.assertIn('os.date("%Y-%m-%d")', command.group(1))

    def test_tmux_session_hook_propagates_attach_failure_through_logger(self) -> None:
        tmux_config = (ROOT / "config/tmux.conf").read_text()
        [command] = re.findall(
            r"bash -o pipefail -c '([^']*attach-session\.sh[^']*)'",
            tmux_config,
        )

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            hook = home / ".config/tmux/attach-session.sh"
            hook.parent.mkdir(parents=True)
            hook.write_text("#!/bin/sh\nexit 37\n")
            hook.chmod(0o755)
            binaries = Path(directory) / "bin"
            binaries.mkdir()
            logger = binaries / "logger"
            logger.write_text("#!/bin/sh\ncat >/dev/null\n")
            logger.chmod(0o755)

            result = subprocess.run(
                ["/bin/bash", "-o", "pipefail", "-c", command],
                env=os.environ
                | {"HOME": str(home), "PATH": f"{binaries}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(37, result.returncode)

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
                str(ROOT / "bin"),
                str(mise_shims),
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

    @unittest.skipUnless(shutil.which("zsh"), "zsh is unavailable")
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

        self.assertIn(
            "if less --version >/dev/null 2>&1; then\n"
            "\texport GIT_PAGER=less\n"
            "fi",
            profile,
        )
        self.assertNotIn("if ! less --version", profile)
        languages = (ROOT / "config/helix/languages.toml").read_text()

        self.assertIn("alias pip_upgrade_all=pip-upgrade-all", profile)
        self.assertIn("alias purge_removed=purge-removed", profile)
        self.assertNotIn("pip list --format=freeze", profile)
        self.assertNotIn("pip_upgrade_all ()", profile)
        self.assertNotIn("purge_removed ()", profile)
        self.assertNotIn("tail --lines=+3", profile)
        self.assertIn('$HOME/.config/helix/steel-lsp', languages)
        self.assertNotIn("/home/jyn", languages)
        self.assertNotIn('echo "no supported package manager found"', profile)
        self.assertIn("alias what_belongs=what-belongs", profile)
        self.assertIn("alias what_runs=what-runs", profile)
        self.assertIn("alias what_package=what-package", profile)
        self.assertNotIn("what_belongs ()", profile)
        self.assertNotIn("what_runs ()", profile)
        self.assertNotIn("what_package ()", profile)
        self.assertIn("printf 'remove crontab? [y/N] '", profile)
        self.assertIn('IFS= read -r reply || return', profile)
        self.assertNotIn("crontab -i -l", profile)
        self.assertIn("recipes () (", profile)
        self.assertIn('recipies () { recipes "$@"; }', profile)

    def test_crontab_wrapper_prompts_for_clustered_remove_options(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("crontab() {")
        end = profile.index("\n}\n", start) + 2
        definition = profile[start:end]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "calls"
            crontab = root / "crontab"
            crontab.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$CRONTAB_CALLS"\n')
            crontab.chmod(0o755)
            environment = os.environ | {
                "CRONTAB_CALLS": str(calls),
                "PATH": f"{root}:{os.environ['PATH']}",
            }

            for arguments in (("-ri",), ("-ir",)):
                calls.unlink(missing_ok=True)
                declined = subprocess.run(
                    ["/bin/sh", "-c", definition + '\ncrontab "$@"', "sh", *arguments],
                    input="n\n",
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, declined.returncode, declined.stderr)
                self.assertIn("remove crontab?", declined.stdout)
                self.assertFalse(calls.exists())

            accepted = subprocess.run(
                ["/bin/sh", "-c", definition + '\ncrontab "$@"', "sh", "-ri"],
                input="y\n",
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual("-ri\n", calls.read_text())

            calls.unlink()
            operand = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    definition + '\ncrontab "$@"',
                    "sh",
                    "--",
                    "-report",
                ],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, operand.returncode, operand.stderr)
            self.assertNotIn("remove crontab?", operand.stdout)
            self.assertEqual("-- -report\n", calls.read_text())

    def test_fork_github_uses_portable_cd_without_calling_shell_wrapper(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("fork_github() {")
        end = profile.index("\n}\n", start) + 2
        definition = profile[start:end]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout with spaces"
            checkout.mkdir()
            helper = root / "fork-github"
            helper.write_text('#!/bin/sh\nprintf "%s\\n" "$CHECKOUT"\n')
            helper.chmod(0o755)
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    definition
                    + '\ncd() { return 99; }\nfork_github || exit\ncommand pwd',
                ],
                env=os.environ
                | {
                    "CHECKOUT": str(checkout),
                    "PATH": f"{root}:{os.environ['PATH']}",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{checkout}\n{checkout}\n", result.stdout)

    def test_make_helpers_preserve_numeric_targets_and_recipe_bodies(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("tasks () (")
        end = profile.index("\nrecipies ()", start)
        definitions = profile[start:end]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make = root / "make"
            make.write_text(
                "#!/bin/sh\n"
                "printf '# File\\n\\n1: dependency\\n\\tprintf body\\n\\n"
                "named: dependency\\n\\tprintf other\\n\\n"
                "%%.generated: %%.source\\n\\tprintf body: # recipe text\\n"
                "\\t# comment-like recipe line\\n\\n"
                ".PHONY: named\\n\\n"
                "# Finished Make data base\\n'\n"
            )
            make.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", "-c", definitions + "\ntasks; printf -- '---\\n'; recipes"],
                env=os.environ | {"PATH": f"{root}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "1\nnamed\n%.generated\n---\n1: dependency\n\tprintf body\n"
            "named: dependency\n\tprintf other\n"
            "%.generated: %.source\n\tprintf body: # recipe text\n"
            "\t# comment-like recipe line\n",
            result.stdout,
        )

    def test_make_helpers_propagate_make_failure_without_partial_output(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("tasks () (")
        end = profile.index("\nrecipies ()", start)
        definitions = profile[start:end]

        with tempfile.TemporaryDirectory() as directory:
            make = Path(directory) / "make"
            make.write_text("#!/bin/sh\nprintf 'partial database\\n'\nexit 23\n")
            make.chmod(0o755)
            environment = os.environ | {"PATH": f"{directory}:{os.environ['PATH']}"}
            tasks = subprocess.run(
                ["/bin/sh", "-c", definitions + "\ntasks"],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            recipes = subprocess.run(
                ["/bin/sh", "-c", definitions + "\nrecipes"],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        for result in (tasks, recipes):
            self.assertEqual(23, result.returncode)
            self.assertEqual("", result.stdout)

    def test_background_uses_nohup_when_disown_is_unavailable(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("background () {")
        end = profile.index("\n}\n", start) + 2
        definition = profile[start:end].replace(
            "command -v disown >/dev/null 2>&1", "false"
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "calls"
            nohup = root / "nohup"
            nohup.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > "{calls}"\n')
            nohup.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", "-c", definition + "\nbackground tool 'two words'; wait"],
                env=os.environ | {"PATH": f"{root}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )
            call_text = calls.read_text()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("tool two words\n", call_text)

    def test_profile_does_not_define_aliases_from_failed_abbreviation_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            binaries = root / "bin"
            home.mkdir()
            binaries.mkdir()
            (home / ".profile").symlink_to(ROOT / "config/profile")
            grep = binaries / "grep"
            grep.write_text(
                "#!/bin/sh\nprintf 'profile_test_alias=printf partial\\n'\nexit 41\n"
            )
            grep.chmod(0o755)
            ls = binaries / "ls"
            ls.write_text("#!/bin/sh\nexit 0\n")
            ls.chmod(0o755)

            result = subprocess.run(
                [
                    "/bin/bash",
                    "--noprofile",
                    "--norc",
                    "-ic",
                    'set -- startup; source "$HOME/.profile"; profile_status=$?; '
                    "if alias profile_test_alias >/dev/null 2>&1; then "
                    "alias_status=defined; else alias_status=missing; fi; "
                    'printf "%s:%s\\n" "$profile_status" "$alias_status"',
                ],
                cwd=root,
                env=os.environ
                | {
                    "BASH_PROFILE_READ": "1",
                    "HOME": str(home),
                    "PATH": f"{binaries}:/usr/bin:/bin",
                    "SSH_AUTH_SOCK": "present",
                    "TERM": "dumb",
                },
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("41:missing\n", result.stdout)

    def test_prompt_adapter_discards_partial_failed_render(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("prompt_adapter() (")
        end = profile.index("\n)\n", start) + 3
        definition = profile[start:end]

        with tempfile.TemporaryDirectory() as directory:
            renderer = Path(directory) / "prompt-command"
            renderer.write_text("#!/bin/sh\nprintf partial\nexit 23\n")
            renderer.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", "-c", definition + "\nprompt_adapter 9"],
                env=os.environ | {"PATH": f"{directory}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("\n; ", result.stdout)
        self.assertNotIn("partial", result.stdout)

    def test_prompt_adapter_installs_complete_multiline_render(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("prompt_adapter() (")
        end = profile.index("\n)\n", start) + 3
        definition = profile[start:end]

        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory) / "calls"
            renderer = Path(directory) / "prompt-command"
            renderer.write_text(
                "#!/bin/sh\n"
                f'printf "%s|%s\\n" "$COLUMNS" "$*" > "{calls}"\n'
                "printf 'first\\nsecond'\n"
            )
            renderer.chmod(0o755)
            result = subprocess.run(
                ["/bin/sh", "-c", definition + "\nCOLUMNS=42; prompt_adapter 7"],
                env=os.environ | {"PATH": f"{directory}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )
            call_text = calls.read_text()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("first\nsecond", result.stdout)
        self.assertEqual("42|bash 7 0 sh\n", call_text)

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

    def test_git_uses_installed_global_hooks(self) -> None:
        result = subprocess.run(
            [
                "git",
                "config",
                "--no-includes",
                "-f",
                str(ROOT / "config/gitconfig"),
                "--get",
                "core.hooksPath",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("~/.config/git/hooks\n", result.stdout)

    def test_remember_does_not_write_terminal_escapes_to_a_pipe(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("remember() {")
        end = profile.index("\n}\n", start) + 2

        result = subprocess.run(
            ["/bin/sh", "-c", profile[start:end] + "\nremember"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_glide_repository_urls_drop_page_routes_and_query_data(self) -> None:
        algorithms = (ROOT / "config/glide-algorithms.ts").as_uri()
        cases = {
            "https://github.com/org/repo/issues/1?q=x#note": [
                "https://github.com/org/repo",
                "repo",
            ],
            "https://gitlab.com/group/subgroup/repo/-/issues/1?q=x#note": [
                "https://gitlab.com/group/subgroup/repo",
                "repo",
            ],
            "https://gitlab.com/group/subgroup/repo.git": [
                "https://gitlab.com/group/subgroup/repo.git",
                "repo",
            ],
        }
        script = (
            "globalThis.glide = {g: {}};\n"
            + f'await import("{algorithms}");\n'
            + "const {repository_from_url} = glide.g.dotfiles_algorithms;\n"
            + "const cases = "
            + json.dumps(list(cases))
            + ";\nfor (const value of cases) {\n"
            + "  const result = repository_from_url(value);\n"
            + "  console.log(JSON.stringify([result.url.toString(), result.repo]));\n"
            + "}\n"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        actual = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(list(cases.values()), actual)

        malformed = [
            "not a URL",
            "https://example.com/org/repo",
            "https://github.com/org",
            "https://gitlab.com/group/-/issues/1",
        ]
        script = (
            "globalThis.glide = {g: {}};\n"
            + f'await import("{algorithms}");\n'
            + "const {repository_from_url} = glide.g.dotfiles_algorithms;\n"
            + f"for (const value of {json.dumps(malformed)}) {{\n"
            + "  try { repository_from_url(value); console.log('accepted'); }\n"
            + "  catch { console.log('rejected'); }\n"
            + "}\n"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["rejected"] * len(malformed), result.stdout.splitlines())

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_glide_disabled_sites_restore_normal_mode_on_exit(self) -> None:
        glide = (ROOT / "config/glide.ts").read_text()
        start = glide.index("async function disable_shortcuts")
        end = glide.index("const disabled_sites", start)
        implementation = glide[start:end]
        script = (
            "const calls = [];\n"
            + "const glide = {excmds: {execute(command) { calls.push(command); }}};\n"
            + implementation
            + "const cleanup = await disable_shortcuts();\n"
            + "await cleanup();\n"
            + "process.stdout.write(JSON.stringify(calls));\n"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["mode_change ignore", "mode_change normal"], json.loads(result.stdout))

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_glide_hint_labels_are_short_and_distinct(self) -> None:
        algorithms = (ROOT / "config/glide-algorithms.ts").as_uri()
        cases = [
            (["a", "b", "c"], ["a", "b", "c"]),
            (["", "", ""], ["0", "1", "2"]),
            (["abcdefg", "ac"], ["ab", "ac"]),
            (["abcdefg", "abcdfff"], ["abc", "abd"]),
            (["apple", "application"], ["app", "apl"]),
            (["test", "test", "testing"], ["tes", "tet", "tei"]),
            (["", "a", ""], ["0", "a", "1"]),
            (["猫", "猫", "café"], ["0", "1", "c"]),
        ]
        script = (
            "globalThis.glide = {g: {}};\n"
            + f'await import("{algorithms}");\n'
            + "const {hint_labels} = glide.g.dotfiles_algorithms;\n"
            + "const elements = INPUT.map(textContent => ({textContent, ariaLabel: null}));\n"
            + "process.stdout.write(JSON.stringify(hint_labels(elements)));"
        )

        for texts, expected in cases:
            result = subprocess.run(
                ["node", "--input-type=module", "-e", f"const INPUT = {texts!r};\n{script}"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(expected, json.loads(result.stdout))

        fallback_script = script.replace(
            "const elements = INPUT.map(textContent => ({textContent, ariaLabel: null}));",
            "const elements = INPUT;",
        )
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                "const INPUT = [{textContent: null, ariaLabel: 'Settings'}];\n"
                + fallback_script,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["s"], json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
