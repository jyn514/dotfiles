#!/usr/bin/env python3

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProfileContractTests(unittest.TestCase):
    def tmux_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            server = "profile-test-" + uuid.uuid4().hex
            command = ["tmux", "-L", server]
            environment = os.environ | {"HOME": directory, "TMUX": "", "PATH": "/usr/bin:/bin"}
            try:
                result = subprocess.run(
                    [*command, "-f", str(ROOT / "config/tmux/tmux.conf"),
                     "new-session", "-d", "-s", "profile-test", "sleep 60"],
                    env=environment, text=True, capture_output=True, timeout=10,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                return subprocess.run([*command, "list-keys", "-F", "#{key_command}"],
                                      env=environment, text=True, capture_output=True,
                                      check=True, timeout=10).stdout
            finally:
                subprocess.run([*command, "kill-server"], env=environment,
                               text=True, capture_output=True, timeout=10)

    def run_profile(self, command, *, env=None, arguments=(), input=None, shell="/bin/bash", interactive=True):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".profile").symlink_to(ROOT / "config/profile")
            (home / ".bashrc").touch()
            (home / ".zshrc").touch()
            environment = os.environ | {
                "HOME": str(home), "PATH": "/usr/bin:/bin", "SSH_AUTH_SOCK": "present",
                "TERM": "dumb", "TMUX": "", "TMUX_PANE": "", "KITTY_INSTALLATION_DIR": "",
                "BASH_PROFILE_READ": "1", "ZSH_PROFILE_READ": "1",
            } | (env or {})
            environment["HOME"] = str(home)
            environment["ENV"] = ""
            environment["XDG_CONFIG_HOME"] = str(home / ".config")
            environment["PROFILE_FISH"] = str(ROOT / "config/config.fish")
            fixture = "profile_command.fish" if Path(shell).name == "fish" else "profile_command.sh"
            return subprocess.run(
                [shell, *(["-i"] if interactive else []), str(ROOT / "tests/setup/fixtures" / fixture), command, *arguments],
                cwd=home, env=environment, input=input, text=True, capture_output=True, timeout=15,
            )

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
        result = self.run_profile('printf "%s\\n" "$MAKEFLAGS"')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertRegex(result.stdout, r"^-j[1-9][0-9]*\n$")

    def test_interactive_shells_apply_environment_activation_after_clearing_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory)
            (tools / "mise").symlink_to(ROOT / "tests/setup/fixtures/mise_activation.sh")
            environment = {
                "PATH": f"{tools}:/usr/bin:/bin", "PROFILE_MISE_TOOLS": str(tools),
                "MISE_SHELL": "stale", "__MISE_DIFF": "stale",
                "__MISE_SESSION": "stale", "__MISE_ORIG_PATH": "stale",
            }
            for shell in ("/bin/bash", "/bin/zsh"):
                if not Path(shell).exists():
                    continue
                with self.subTest(shell=shell):
                    result = self.run_profile('printf "%s\\n" "$DOTFILES_MISE_ACTIVE"',
                                              env=environment, shell=shell)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("yes\n", result.stdout)

    def test_dotfile_commands_keep_precedence_after_environment_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory)
            (tools / "mise").symlink_to(ROOT / "tests/setup/fixtures/mise_activation.sh")
            (tools / "copy").write_text("#!/bin/sh\nexit 99\n")
            (tools / "copy").chmod(0o755)
            result = self.run_profile('command -v copy', env={
                "PATH": f"{tools}:/usr/bin:/bin", "PROFILE_MISE_TOOLS": str(tools),
            })
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(str(ROOT / "bin/copy") + "\n", result.stdout)

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

    @unittest.skipUnless(shutil.which("tmux"), "tmux is unavailable")
    def test_tmux_paste_bindings_do_not_paste_after_clipboard_failure(self) -> None:
        tmux_config = self.tmux_bindings()
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

    @unittest.skipUnless(shutil.which("tmux"), "tmux is unavailable")
    def test_tmux_copy_actions_pass_hostile_text_as_one_argument(self) -> None:
        # Inspect tmux's parsed, quoted command arguments rather than the
        # configuration's choice of quotes, braces, and line continuations.
        commands = [argument.removeprefix("cd #{q:pane_current_path}; ")
                    for line in self.tmux_bindings().splitlines()
                    for argument in shlex.split(line)
                    if argument.startswith("cd #{q:pane_current_path}; ")]
        dragon_commands = [command for command in commands
                           if command.endswith("~/.config/tmux/dragon.sh --read0")]
        self.assertEqual(2, len(dragon_commands))
        actions = {}
        for action in ("search", "open", "edit"):
            matches = [command for command in commands
                       if command.endswith(f"~/.config/tmux/picker-action {action} --read0")]
            self.assertEqual(1, len(matches), action)
            actions[action] = matches[0]

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
                    '#!/bin/sh\n'
                    'case ${0##*/} in\n'
                    'dragon) [ "$#" = 2 ] || exit 41;;\n'
                    'open) [ "$#" = 1 ] || exit 42;;\n'
                    'esac\n'
                    'printf "%s" "$*" > "$ACTION_CALLS"\n'
                )
                executable.chmod(0o755)
            env = os.environ | {
                "ACTION_CALLS": str(calls),
                "PATH": f"{binaries}:{os.environ['PATH']}",
            }

            for command in dragon_commands:
                command = command.replace(
                    "~/.config/tmux/dragon.sh", str(ROOT / "libexec/tmux/dragon.sh")
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

            command = actions["open"].replace(
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

            command = actions["edit"].replace(
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

            command = actions["search"].replace(
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

    @unittest.skipUnless(shutil.which("zsh"), "Zsh is unavailable")
    def test_zsh_sudo_preserves_current_input_and_uses_history_only_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            antidote = home / "antidote"
            antidote.mkdir()
            (antidote / "antidote.zsh").symlink_to(ROOT / "tests/setup/fixtures/antidote.zsh")
            result = subprocess.run(
                ["zsh", "-f", "-i", str(ROOT / "tests/setup/fixtures/zsh_sudo_widget.zsh")],
                cwd=home, env=os.environ | {
                    "HOME": str(home), "ZDOTDIR": str(home), "DOTFILES": str(ROOT),
                    "PROFILE_ZSH": str(ROOT / "config/zsh/.zshrc"), "PATH": "/usr/bin:/bin",
                    "TERM": "dumb", "TMUX": "", "KITTY_INSTALLATION_DIR": "",
                }, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)



    @unittest.skipUnless(shutil.which("fish"), "Fish is unavailable")
    def test_directory_completions_read_the_current_token_at_each_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "zoxide").symlink_to(ROOT / "tests/setup/fixtures/zoxide_query.sh")
            calls = root / "queries"
            result = subprocess.run(
                ["fish", str(ROOT / "tests/setup/fixtures/z_completion.fish")],
                cwd=root, env=os.environ | {"HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"),
                    "PATH": f"{root}:/usr/bin:/bin", "PROFILE_Z": str(ROOT / "config/z.fish"),
                    "Z_QUERY_LOG": str(calls)}, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            queries = calls.read_text().splitlines()
            self.assertEqual(2, len(queries))
            self.assertTrue(queries[0].endswith("-- first"), queries)
            self.assertTrue(queries[1].endswith("-- second"), queries)

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
                PATH=f"{mise_shims}:{local_bin}:/usr/bin:{mise_shims}:{local_bin}",
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
                str(local_bin),
                str(cargo_bin),
            ]
            self.assertEqual(expected_prefix, paths[: len(expected_prefix)])
            self.assertEqual(1, paths.count(str(local_bin)))
            self.assertEqual(1, paths.count(str(cargo_bin)))
            self.assertNotIn(str(mise_shims), paths)

    def test_noninteractive_profile_evaluates_only_successful_mise_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            binaries = home / ".local/bin"
            binaries.mkdir(parents=True)
            (home / ".profile").symlink_to(ROOT / "config/profile")
            (binaries / "mise").symlink_to(ROOT / "tests/setup/fixtures/mise_environment.sh")
            for exit_status, applied in ((0, "yes"), (37, "unset")):
                with self.subTest(exit_status=exit_status):
                    result = subprocess.run(
                        ["/bin/sh", "-c", '. "$HOME/.profile"; profile_status=$?; '
                         'printf "%s:%s:%s\\n" "$profile_status" '
                         '"${DOTFILES_MISE_ENV_APPLIED-unset}" "${mise_environment-unset}"'],
                        cwd=ROOT,
                        env=os.environ | {"HOME": str(home), "PATH": "/usr/bin:/bin",
                                          "SSH_AUTH_SOCK": "present",
                                          "DOTFILES_MISE_ENV_EXIT": str(exit_status)},
                        text=True, capture_output=True,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(f"{exit_status}:{applied}:unset\n", result.stdout)

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
                    str(ROOT / "config/zsh/.zshrc"),
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
            env.update(HOME=str(home), SSH_AUTH_SOCK="", PATH="/usr/bin:/bin")

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

    def test_profile_installs_aliases_for_native_command_entrypoints(self) -> None:
        aliases = {
            "pip_upgrade_all": "pip-upgrade-all", "purge_removed": "purge-removed",
            "what_belongs": "what-belongs", "what_runs": "what-runs", "what_package": "what-package",
        }
        result = self.run_profile('alias "$@"', arguments=list(aliases), shell="/bin/sh")
        self.assertEqual(0, result.returncode, result.stderr)
        for alias, command in aliases.items():
            self.assertIn(f"{alias}='{command}'", result.stdout.splitlines())

    def test_profile_selects_less_only_when_the_command_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "less"
            executable.write_text('#!/bin/sh\nexit "$PROFILE_LESS_EXIT"\n')
            executable.chmod(0o755)
            for exit_status, pager in ((0, "less"), (23, "original-pager")):
                with self.subTest(exit_status=exit_status):
                    result = self.run_profile('printf "%s\\n" "$GIT_PAGER"', env={
                        "PATH": f"{directory}:/usr/bin:/bin", "GIT_PAGER": "original-pager",
                        "PROFILE_LESS_EXIT": str(exit_status),
                    })
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(pager + "\n", result.stdout)

    def test_helix_language_server_expands_the_callers_home(self) -> None:
        server = tomllib.loads((ROOT / "config/helix/languages.toml").read_text())["language-server"]["steel"]
        with tempfile.TemporaryDirectory(prefix="helix home with spaces ") as directory:
            root = Path(directory)
            executable = root / "steel-language-server"
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$STEEL_LSP_HOME"\n')
            executable.chmod(0o755)
            result = subprocess.run([server["command"], *server["args"]],
                env=os.environ | {"HOME": str(root), "PATH": f"{root}:/usr/bin:/bin"},
                text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(str(root / ".config/helix/steel-lsp") + "\n", result.stdout)

    def test_crontab_wrapper_prompts_for_clustered_remove_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "calls"
            crontab = root / "crontab"
            crontab.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$CRONTAB_CALLS"\n')
            crontab.chmod(0o755)
            environment = os.environ | {
                "CRONTAB_CALLS": str(calls),
                "PROFILE_TEST_BIN": str(root), "PATH": "/usr/bin:/bin",
            }

            for arguments in (("-ri",), ("-ir",)):
                calls.unlink(missing_ok=True)
                declined = self.run_profile('crontab "$@"', shell='/bin/sh', arguments=[*arguments], input='n\n', env=environment)
                self.assertEqual(0, declined.returncode, declined.stderr)
                self.assertIn("remove crontab?", declined.stdout)
                self.assertFalse(calls.exists())

            accepted = self.run_profile('crontab "$@"', shell='/bin/sh', arguments=['-ri'], input='y\n', env=environment)
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual("-ri\n", calls.read_text())

            calls.unlink()
            operand = self.run_profile('crontab "$@"', shell='/bin/sh', arguments=['--', '-report'], env=environment)
            self.assertEqual(0, operand.returncode, operand.stderr)
            self.assertNotIn("remove crontab?", operand.stdout)
            self.assertEqual("-- -report\n", calls.read_text())

    def test_fork_github_uses_portable_cd_without_calling_shell_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout with spaces"
            checkout.mkdir()
            helper = root / "fork-github"
            helper.write_text('#!/bin/sh\nprintf "%s\\n" "$CHECKOUT"\n')
            helper.chmod(0o755)
            result = self.run_profile('cd() { return 99; }; fork_github || exit; command pwd', shell='/bin/sh', env=os.environ | {'CHECKOUT': str(checkout), 'PROFILE_TEST_BIN': str(root), 'PATH': '/usr/bin:/bin'})

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"{checkout}\n{checkout}\n", result.stdout)

    def test_make_helpers_preserve_numeric_targets_and_recipe_bodies(self) -> None:
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
            result = self.run_profile("tasks; printf -- '---\\n'; recipes", shell='/bin/sh', env=os.environ | {'PROFILE_TEST_BIN': str(root), 'PATH': '/usr/bin:/bin'})
            alias = self.run_profile("recipies", shell='/bin/sh', env={"PROFILE_TEST_BIN": str(root)})

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0, alias.returncode, alias.stderr)
        self.assertEqual(result.stdout.split("---\n", 1)[1], alias.stdout)
        self.assertEqual(
            "1\nnamed\n%.generated\n---\n1: dependency\n\tprintf body\n"
            "named: dependency\n\tprintf other\n"
            "%.generated: %.source\n\tprintf body: # recipe text\n"
            "\t# comment-like recipe line\n",
            result.stdout,
        )

    def test_make_helpers_propagate_make_failure_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            make = Path(directory) / "make"
            make.write_text("#!/bin/sh\nprintf 'partial database\\n'\nexit 23\n")
            make.chmod(0o755)
            environment = os.environ | {"PROFILE_TEST_BIN": directory, "PATH": "/usr/bin:/bin"}
            tasks = self.run_profile('tasks', shell='/bin/sh', env=environment)
            recipes = self.run_profile('recipes', shell='/bin/sh', env=environment)

        for result in (tasks, recipes):
            self.assertEqual(23, result.returncode)
            self.assertEqual("", result.stdout)

    def test_background_uses_nohup_when_disown_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "calls"
            nohup = root / "nohup"
            nohup.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > "{calls}"\n')
            nohup.chmod(0o755)
            result = self.run_profile("enable -n disown; background tool 'two words'; wait",
                                      env={"PROFILE_TEST_BIN": str(root)})
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
        with tempfile.TemporaryDirectory() as directory:
            renderer = Path(directory) / "prompt-command"
            renderer.write_text("#!/bin/sh\nprintf partial\nexit 23\n")
            renderer.chmod(0o755)
            result = self.run_profile('prompt_adapter 9', shell='/bin/bash', env=os.environ | {'PROFILE_TEST_BIN': directory, 'PATH': '/usr/bin:/bin'})

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("\n; ", result.stdout)
        self.assertNotIn("partial", result.stdout)

    def test_prompt_adapter_installs_complete_multiline_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory) / "calls"
            renderer = Path(directory) / "prompt-command"
            renderer.write_text(
                "#!/bin/sh\n"
                f'printf "%s|%s\\n" "$COLUMNS" "$*" > "{calls}"\n'
                "printf 'first\\nsecond'\n"
            )
            renderer.chmod(0o755)
            result = self.run_profile('COLUMNS=42; prompt_adapter 7', shell='/bin/bash', env=os.environ | {'PROFILE_TEST_BIN': directory, 'PATH': '/usr/bin:/bin'})
            call_text = calls.read_text()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("first\nsecond", result.stdout)
        self.assertEqual("42|bash 7 0 profile_command.sh\n", call_text)

    def test_git_merge_request_alias_passes_hostile_remote_as_one_argument(self) -> None:
        alias = subprocess.run(
            ["git", "config", "--no-includes", "-f", str(ROOT / "config/gitconfig"), "--get", "alias.mr"],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["jj", "git", "init", str(root)], check=True, capture_output=True)
            spy = root / "git"
            spy.symlink_to(ROOT / "tests/setup/fixtures/record_git.py")
            calls = root / "calls.jsonl"
            marker = root / "injected"
            remote = f"a remote; touch {marker}; $(touch {marker})"
            result = subprocess.run([shutil.which("git"), "-c", f"alias.mr={alias}", "mr", remote, "42"],
                cwd=root,
                env=os.environ | {"PATH": f"{root}:/usr/bin:/bin", "GIT_EXEC_PATH": str(root),
                                  "GIT_TEST_LOG": str(calls)},
                text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual([["fetch", remote, "merge-requests/42/head:mr-42"], ["checkout", "mr-42"]],
                             [json.loads(line) for line in calls.read_text().splitlines()])
            self.assertFalse(marker.exists())

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
        result = self.run_profile('remember')
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
    def test_glide_registered_callbacks_handle_urls_modes_and_hint_labels(self) -> None:
        result = subprocess.run(
            [
                "node",
                str(ROOT / "tests/setup/fixtures/glide-url-autocmd.mjs"),
                str(ROOT / "config/glide.ts"),
            ],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)



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

        content_script = (
            "globalThis.glide = {g: {}};\n"
            + f'await import("{algorithms}");\n'
            + "const {hint_labels_from_content} = glide.g.dotfiles_algorithms;\n"
            + "const content = {async map(callback) {\n"
            + "  return [{textContent: 'Settings', ariaLabel: null}].map(callback);\n"
            + "}};\n"
            + "process.stdout.write(JSON.stringify(await hint_labels_from_content(content)));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", content_script],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["s"], json.loads(result.stdout))




if __name__ == "__main__":
    unittest.main()
