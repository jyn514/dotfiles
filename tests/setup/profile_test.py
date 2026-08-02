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
        self.assertIsNotNone(search_command)
        self.assertIsNotNone(open_command)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            calls = root / "calls"
            marker = root / "injected"
            payload = f"odd ' $(touch {marker})\nname"
            for name in ("dragon", "open"):
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
            "1\nnamed\n---\n1: dependency\n\tprintf body\n"
            "named: dependency\n\tprintf other\n",
            result.stdout,
        )

    def test_background_uses_nohup_when_disown_is_unavailable(self) -> None:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("background () {")
        end = profile.index("\n}\n", start) + 2
        definition = profile[start:end]

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

    def test_profile_checks_abbreviation_loading_before_defining_aliases(self) -> None:
        profile = (ROOT / "config/profile").read_text()

        self.assertIn(
            "abbreviations=$(grep -Ev '^(#|$)' \"$DOTFILES/lib/abbr.txt\") || return",
            profile,
        )
        self.assertIn('eval "$snap_bin" || {', profile)
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

    def test_path_consumers_and_comment_regex_preserve_literal_text(self) -> None:
        tmux = (ROOT / "config/tmux.conf").read_text()
        nvim = (ROOT / "config/nvim.lua").read_text()
        glide = (ROOT / "config/glide.ts").read_text()
        fish = (ROOT / "config/config.fish").read_text()
        kakoune = (ROOT / "config/kakrc").read_text()
        julia = (ROOT / "config/startup.jl").read_text()
        profile = (ROOT / "config/profile").read_text()
        vimrc = (ROOT / "config/vimrc").read_text()
        zprofile = (ROOT / "config/zprofile").read_text()

        self.assertNotIn("; xargs open", tmux)
        self.assertEqual(1, tmux.count("xargs -0"))
        self.assertEqual(5, tmux.count("bash -o pipefail -c"))
        self.assertNotIn("tmux load-buffer -b clipboard -;", tmux)
        self.assertNotIn("tmux load-buffer -b primary_selection -;", tmux)
        self.assertIn("if (save != \\\"\\\")", tmux)
        self.assertIn('vim.fn.escape(comment, "\\\\/.*$^~[]")', nvim)
        self.assertIn('pickers.git_status({ prompt = "Changed Files" })', nvim)
        self.assertNotIn(
            'cmd = "git ls-files --cached --others --exclude-standard"', nvim
        )
        self.assertIn(
            "pickers.lsp_document_diagnostics, { desc = \"Show document diagnostics\" }",
            nvim,
        )
        self.assertIn("buffer = buf,\n\t\tcallback", nvim)
        for variable in ("selections", "swaps", "moves", "upper"):
            self.assertIn(f"local {variable} =", nvim)
        self.assertIn("local function indentgroup(lang, func)", nvim)
        self.assertIn("lang .. 'indent', { clear = true }", nvim)
        self.assertNotRegex(nvim, r"(?m)^function indentgroup\(")
        self.assertIn("function spaces(count, global)\n\tlocal opt", nvim)
        self.assertEqual(1, glide.count('glide.keymaps.set("normal", "U"'))
        self.assertIn('os === "mac" ? "<D-S-z>" : "<C-S-z>"', glide)
        self.assertEqual(2, glide.count("if (currentTab?.id == null) return;"))
        self.assertIn("if (next?.id == null) return;", glide)
        self.assertIn("if (tab?.id == null) return;", glide)
        self.assertIn("if (selection == null) return;", glide)
        self.assertIn("function strip(text: string | null)", glide)
        self.assertIn('return (text ?? "").replace', glide)
        for variable in ("paredit", "comment_api", "MiniStatusline", "wk"):
            self.assertIn(f"local {variable} =", nvim)
        for helper in (
            "abbrev",
            "autosave_disable",
            "autosave_enable",
            "bind",
            "bind_ts",
            "buffer_delete",
            "set_spider",
        ):
            self.assertIn(f"local function {helper}(", nvim)
            self.assertNotRegex(nvim, rf"(?m)^function {helper}\(")
        self.assertNotIn("function BufferDelete(", nvim)
        self.assertIn("bind_ts(ts {", nvim)
        self.assertIn("}, { buffer = args.buf })", nvim)
        self.assertIn('rg_opts = [[--color=never --files -g "!.git" -g "!.jj"', nvim)
        self.assertIn("fd_opts = [[--color=never --type f --type l --exclude .git --exclude .jj", nvim)
        self.assertIn('pickers.git_files({ winopts = { title = "All tracked files" } })', nvim)
        self.assertIn('desc = "Open file picker (all tracked files)"', nvim)
        self.assertIn('vim.fs.basename(opts.file) == "main.typ"', nvim)
        self.assertNotIn('string.match(opts.file, "main.typ$")', nvim)
        self.assertIn("vim.lsp.codelens.refresh { bufnr = bufnr }", nvim)
        self.assertNotIn('nvim_create_autocmd({ "BufEnter", "LspAttach" }', nvim)
        self.assertNotIn("\n_ = [[\n", nvim)
        self.assertIn("<A-ScrollWheelDown>', '<C-d>', { desc = 'Scroll page down'", nvim)
        self.assertIn("<A-ScrollWheelUp>', '<C-u>', { desc = 'Scroll page up'", nvim)
        self.assertEqual(4, nvim.count("vim.fn.fnameescape("))
        self.assertNotIn("'edit ' .. config", nvim)
        self.assertNotIn("'source ' .. config", nvim)
        self.assertIn("*.h,*.c set filetype=c", vimrc)
        self.assertIn("*.cc,*.cpp,*.C,*.ino set filetype=cpp", vimrc)
        self.assertNotIn("*.h,*.c,*.cc", vimrc)
        self.assertIn("augroup dotfiles_config\nautocmd!", vimrc)
        self.assertIn("augroup dotfiles_checktime\n\tautocmd!", vimrc)
        self.assertNotIn("\nau FocusGained,BufEnter", vimrc)
        self.assertEqual(1, vimrc.count("augroup dotfiles_config"))
        self.assertIn("let l:status = v:shell_error", vimrc)
        self.assertIn("return l:status", vimrc)
        self.assertIn("function! CompileTex()", vimrc)
        for option in ("tabstop", "shiftwidth", "softtabstop"):
            self.assertNotRegex(vimrc, rf"\n\tset {option}=")
            self.assertIn(f"\n\tsetlocal {option}=", vimrc)
        self.assertIn(
            "setglobal tabstop=2 shiftwidth=2 softtabstop=2 expandtab", vimrc
        )
        self.assertIn("autocmd FileType tex inoremap <buffer> <C-l>", vimrc)
        self.assertIn("autocmd FileType tex nnoremap <buffer> <C-l>", vimrc)
        self.assertNotIn("\ninoremap <C-l>", vimrc)
        self.assertNotIn("\nnnoremap <C-l>", vimrc)
        self.assertIn("fnamemodify(l:source, ':h')", vimrc)
        self.assertIn("' && cd ' . shellescape(l:directory)", vimrc)
        self.assertIn("shellescape(l:build)", vimrc)
        self.assertIn("shellescape(l:filename)", vimrc)
        self.assertIn("silent! unmap <TAB>", vimrc)
        self.assertEqual(7, vimrc.count("function! "))
        self.assertNotIn("\nfunction ", vimrc)
        self.assertIn("Plug 'vim-latex/vim-latex', { 'for': 'tex' }", vimrc)
        self.assertNotIn("{ 'for': 'latex' }", vimrc)
        self.assertIn("ZSH_PROFILE_READ=1\n. ~/.profile || return", zprofile)
        self.assertNotIn('awk -v arg="$1"', profile)
        self.assertIn('command open-man-page "$@"', profile)
        self.assertIn('[ "$status" -eq 69 ] || return "$status"', profile)
        self.assertIn('kak-lsp --kakoune -s "$kak_session"', kakoune)
        self.assertNotIn('kak-lsp --kakoune -s $kak_session', kakoune)
        self.assertIn('define_editor("editor-hax", wait=true)', julia)
        self.assertNotIn('define_editor("hx-hax"', julia)
        self.assertIn("export JULIA_EDITOR=editor-hax", profile)
        self.assertIn("export JULIA_EDITOR=editor-hax", fish)
        self.assertNotIn("JULIA_EDITOR=hx-hax", profile + fish)
        self.assertNotIn("xargs -I {}", tmux)
        self.assertEqual(1, tmux.count("xargs -0"))
        self.assertIn("picker-action open --read0", tmux)
        self.assertIn("picker-action search --read0", tmux)
        self.assertNotIn('urlencode({"q": sys.argv[1]})', tmux)
        self.assertNotIn("arg=\"'\"$1\"'\"", profile)
        self.assertNotIn('rg "^$1"', profile)
        self.assertIn("man() {\n\t\t\tlocal status", profile)
        self.assertNotIn("\n\t\t\tcheck()", profile)
        self.assertIn("local existing new_path old_ifs p restore_glob", profile)
        self.assertIn("crontab() {\n\tlocal argument options reply", profile)
        self.assertIn("fork_github() {\n\tlocal dir", profile)
        self.assertIn('bash --norc --noprofile "$@"', profile)
        self.assertIn("local abbreviations alias expn name", profile)
        self.assertIn("local conflict_diff result", profile)
        self.assertIn("telnet_output=$(telnet", profile)
        self.assertIn('printf \'%s\\n\' "$telnet_output" | tail -2', profile)
        self.assertIn("local marker = vim.fs.find", nvim)
        self.assertIn("return marker and vim.fs.dirname(marker)", nvim)
        self.assertIn("vim.fs.root(buf, { 'package.json', 'tsconfig.json' })", nvim)
        self.assertIn("vim.lsp.config('oxlint', {", nvim)
        self.assertNotIn("vim.lsp.config('oxc', {", nvim)
        self.assertIn(
            "'markdown_oxide', 'oxlint', 'perlnavigator', 'powershell_es', 'tinymist'",
            nvim,
        )
        self.assertIn("if not first_run then vim.lsp.enable(lsp, false) end", nvim)
        self.assertNotIn("LspRestart", nvim)
        self.assertNotIn("vim.fs.root(0, { 'package.json'", nvim)
        self.assertIn("codelens.refresh { bufnr = bufnr }", nvim)
        self.assertNotIn("codelens.refresh { bufnr = 0 }", nvim)
        self.assertIn("if win >= 0 then vim.lsp.foldclose('imports', win) end", nvim)
        self.assertIn("nvim_set_hl(0, 'mumpsCommand', { link = 'Special' })", nvim)
        self.assertIn("nvim_set_hl(0, 'mumpsZCommand', { link = 'Special' })", nvim)
        self.assertNotIn("highlight! link Keyword Special", nvim)
        self.assertIn("return s:match'^(.*%S)%s*$' or ''", nvim)
        self.assertIn("local function rtrim(s)", nvim)
        self.assertEqual(
            1,
            nvim.count(
                'nvim_create_augroup("lsp_document_highlight", { clear = true })'
            ),
        )
        self.assertIn("group = lsp_document_highlight", nvim)
        self.assertIn("group = lsp_attach", nvim)
        self.assertIn('desc = "Run codelens", buffer = bufnr', nvim)
        self.assertGreaterEqual(nvim.count("force = true"), 9)
        self.assertIn("local config_group = vim.api.nvim_create_augroup", nvim)
        self.assertIn("local autosave_group = vim.api.nvim_create_augroup", nvim)
        self.assertIn("nvim_get_autocmds({ group = autosave_group, buffer = buf })", nvim)
        self.assertNotIn("local timers = {}", nvim)
        self.assertNotIn("vim.bo.colorcolumn", nvim)
        self.assertIn("vim.api.nvim_create_autocmd({ 'BufEnter', 'FileType' }", nvim)
        self.assertNotIn('pattern = "markdown",\n\tcallback = function()\n\t\tvim.wo.colorcolumn', nvim)
        self.assertIn('encoded=$(printf "%s" "$kak_reg_dquote" | base64) || exit', kakoune)
        self.assertIn("encoded=$(printf '%s' \"$encoded\" | tr -d '\\n') || exit", kakoune)
        self.assertNotIn("base64 | tr", kakoune)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_glide_repository_urls_drop_page_routes_and_query_data(self) -> None:
        glide = (ROOT / "config/glide.ts").read_text()
        start = glide.index("function repository_from_url")
        end = glide.index("// clone repo", start)
        implementation = glide[start:end]
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
            implementation
            + "\nconst cases = "
            + json.dumps(list(cases))
            + ";\nfor (const value of cases) {\n"
            + "  const result = repository_from_url(value);\n"
            + "  console.log(JSON.stringify([result.url.toString(), result.repo]));\n"
            + "}\n"
        )
        result = subprocess.run(
            ["node", "-e", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        actual = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(list(cases.values()), actual)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_glide_hint_labels_are_short_and_distinct(self) -> None:
        glide = (ROOT / "config/glide.ts").read_text()
        start = glide.index("function shorten_unique_prefixes")
        end = glide.index("glide.o.hint_label_generator", start)
        implementation = glide[start:end]
        cases = [
            (["a", "b", "c"], ["a", "b", "c"]),
            (["", "", ""], ["0", "1", "2"]),
            (["abcdefg", "ac"], ["ab", "ac"]),
            (["abcdefg", "abcdfff"], ["abc", "abd"]),
            (["apple", "application"], ["app", "apl"]),
            (["test", "test", "testing"], ["tes", "tet", "tei"]),
            (["", "a", ""], ["0", "a", "1"]),
        ]
        script = implementation + "\nprocess.stdout.write(JSON.stringify(labels(INPUT)));"

        for texts, expected in cases:
            result = subprocess.run(
                ["node", "-e", f"const INPUT = {texts!r};\n{script}"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(expected, json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
