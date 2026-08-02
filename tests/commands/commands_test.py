import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_replace_treats_text_and_filenames_literally(self) -> None:
        nested = self.directory / "directory with spaces"
        nested.mkdir()
        document = nested / "file with spaces"
        document.write_text("before .[]% after .[]%\n")

        result = subprocess.run(
            [str(ROOT / "bin/replace"), ".[]%", r"x&\y$"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("before x&\\y$ after x&\\y$\n", document.read_text())

    def test_viewers_do_not_overwrite_working_directory_files(self) -> None:
        markdown = self.directory / "document.md"
        dot = self.directory / "graph.dot"
        markdown.write_text("heading\n")
        dot.write_text("digraph {}\n")
        existing_html = self.directory / "tmp.html"
        existing_svg = self.directory / "tmp.svg"
        existing_html.write_text("keep html")
        existing_svg.write_text("keep svg")
        opened = self.directory / "opened"
        self.executable("pulldown-cmark", "cat\n")
        self.executable("dot", "cat\n")
        self.executable("sleep", "exit 0\n")
        self.executable("open", 'printf "%s\\n" "$1" >> "$OPENED"\n')
        self.executable("xdg-open", 'printf "%s\\n" "$1" >> "$OPENED"\n')
        environment = os.environ | {
            "OPENED": str(opened),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for command, source in (("view_markdown", markdown), ("view_dot", dot)):
            result = subprocess.run(
                [str(ROOT / f"bin/{command}"), str(source)],
                cwd=self.directory,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(0, result.returncode, result.stderr)

        self.assertEqual("keep html", existing_html.read_text())
        self.assertEqual("keep svg", existing_svg.read_text())
        opened_paths = [Path(path) for path in opened.read_text().splitlines()]
        self.assertEqual(2, len(opened_paths))
        self.assertTrue(all(not path.exists() for path in opened_paths))

    def test_desktop_files_preserves_spaces_in_xdg_directories(self) -> None:
        first = self.directory / "first data"
        second = self.directory / "second data"
        for directory, name in ((first, "first.desktop"), (second, "second.desktop")):
            applications = directory / "applications"
            applications.mkdir(parents=True)
            (applications / name).touch()

        result = subprocess.run(
            [str(ROOT / "bin/desktop-files")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "HOME": str(self.directory / "home"),
                "XDG_DATA_DIRS": f"{first}:{second}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            {first / "applications/first.desktop", second / "applications/second.desktop"},
            {Path(path) for path in result.stdout.splitlines()},
        )

    def test_remote_git_url_handles_spaces_and_blank_lines_offline(self) -> None:
        repository = self.directory / "repository with spaces"
        repository.mkdir()
        source = repository / "file #%? with spaces"
        source.write_text("unique line\n\n")
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'case "$1 $2" in\n'
            '  "rev-parse --show-toplevel") printf "%s\\n" "$REPOSITORY";;\n'
            '  "remote get-url") printf "https://github.com/user/repo.git\\n";;\n'
            '  "remote ") printf "origin\\n";;\n'
            '  "rev-list --remotes") printf "abc123\\n";;\n'
            '  "grep --line-number") printf "abc123:file with spaces\\n1:unique line\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "REPOSITORY": str(repository.resolve()),
        }

        matched = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        blank = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "2"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(1, matched.returncode, matched.stderr)
        self.assertEqual(
            "https://github.com/user/repo/blob/abc123/file%20%23%25%3F%20with%20spaces#L1\n",
            matched.stdout,
            matched.stderr + calls.read_text(),
        )
        self.assertEqual(1, blank.returncode)
        self.assertEqual(
            "https://github.com/user/repo/blob/HEAD/file%20%23%25%3F%20with%20spaces#L2\n",
            blank.stdout,
        )
        call_lines = calls.read_text().splitlines()
        self.assertNotIn("remote set-head --auto origin", call_lines)
        self.assertEqual(1, sum(line.startswith("grep --line-number") for line in call_lines))

    def test_set_tmux_env_preserves_whitespace_and_equals(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "env",
            "printf 'EDITOR=editor --wait\\nPATH=/one path:/two=parts\\n'\n",
        )
        self.executable(
            "tmux",
            'printf "<%s><%s><%s>\\n" "$1" "$2" "$3" >> "$TMUX_CALLS"\n',
        )

        result = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "<set-environment><EDITOR><editor --wait>\n"
            "<set-environment><PATH></one path:/two=parts>\n",
            calls.read_text(),
        )

    def test_set_tmux_env_propagates_profile_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable("env", "exit 17\n")
        self.executable("tmux", 'printf "%s\\n" "$*" > "$TMUX_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(17, result.returncode)
        self.assertFalse(calls.exists())

    def test_renumber_tmux_sessions_avoids_name_collisions(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'if [ "$1" = list-sessions ]; then\n'
            "  printf '10\\n0\\n2\\n'\n"
            "else\n"
            '  printf "%s %s %s\\n" "$1" "$3" "$4" >> "$TMUX_CALLS"\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "config/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        renames = [line.split() for line in calls.read_text().splitlines()]
        self.assertEqual(["0", "2", "10"], [line[1] for line in renames[:3]])
        self.assertEqual(["1", "2", "3"], [line[2] for line in renames[3:]])
        self.assertEqual(
            [line[2] for line in renames[:3]],
            [line[1] for line in renames[3:]],
        )

    def test_renumber_tmux_sessions_propagates_listing_failure(self) -> None:
        self.executable("tmux", "exit 19\n")

        result = subprocess.run(
            [str(ROOT / "config/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(19, result.returncode)

    def test_renumber_tmux_sessions_rolls_back_second_phase_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'if [ "$1" = list-sessions ]; then\n'
            "  printf '10\\n0\\n2\\n'\n"
            "else\n"
            '  printf "%s %s %s\\n" "$1" "$3" "$4" >> "$TMUX_CALLS"\n'
            '  case "$3:$4" in __renumber-tmux-*-2:2) exit 27;; esac\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "config/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(27, result.returncode)
        renames = [line.split() for line in calls.read_text().splitlines()]
        recovery = renames[-3:]
        self.assertEqual(["0", "2", "10"], [line[2] for line in recovery])
        self.assertTrue(all("recovery" in line[1] for line in recovery))

    def test_merge_copies_dotfiles_before_removing_source(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / ".hidden").write_text("kept\n")
        self.executable("stat", "printf 'different-device\\n'\n")

        result = subprocess.run(
            [str(ROOT / "bin/merge"), str(source), str(destination)],
            text=True,
            input="y\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("kept\n", (destination / ".hidden").read_text())
        self.assertFalse(source.exists())

    def test_merge_retains_source_when_destination_entries_are_skipped(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "collision").write_text("source\n")
        (destination / "collision").write_text("destination\n")
        self.executable("stat", "printf 'different-device\\n'\n")
        self.executable("cp", "exit 0\n")

        result = subprocess.run(
            [str(ROOT / "bin/merge"), str(source), str(destination)],
            text=True,
            input="y\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("source\n", (source / "collision").read_text())
        self.assertEqual("destination\n", (destination / "collision").read_text())
        self.assertIn("Source retained", result.stdout)

    def test_makeuser_stops_after_confirmation_is_refused(self) -> None:
        calls = self.directory / "adduser-calls"
        self.executable("adduser", 'printf "%s\\n" "$*" >> "$ADDUSER_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/makeuser"), "citizen", "ssh-ed25519 key"],
            text=True,
            input="n\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "ADDUSER_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("error: aborting", result.stdout)
        self.assertFalse(calls.exists())

    def test_firefox_preserves_spaces_in_windows_path(self) -> None:
        calls = self.directory / "firefox-calls"
        self.executable("wslpath", "printf 'C:\\\\Users\\\\One Esk\\\\page.html\\n'\n")
        self.executable(
            "firefox",
            'printf "%s\\n%s\\n" "$#" "$1" > "$FIREFOX_CALLS"\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/firefox.sh"), "/mnt/c/Users/One Esk/page.html"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "FIREFOX": str(self.directory / "firefox"),
                "FIREFOX_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("1\nC:\\Users\\One Esk\\page.html\n", calls.read_text())

    def test_cargo_doc_dev_accepts_no_subcommand_argument(self) -> None:
        calls = self.directory / "cargo-calls"
        self.executable("cargo", 'printf "%s\\n" "$*" > "$CARGO_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/cargo-doc-dev")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CARGO": str(self.directory / "cargo"),
                "CARGO_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("doc --document-private-items --no-deps\n", calls.read_text())

    def test_git_backup_commands_do_not_overwrite_tar_output(self) -> None:
        calls = self.directory / "git-calls"
        self.executable("git", 'printf "%s\\n" "$*" >> "$GIT_CALLS"\n')

        for command in ("git-save", "git-backup"):
            with self.subTest(command=command):
                output = self.directory / command
                archive = Path(f"{output}.tar")
                archive.write_text("existing\n")
                result = subprocess.run(
                    [str(ROOT / f"bin/{command}"), "repository", str(output)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=os.environ | {
                        "GIT_CALLS": str(calls),
                        "PATH": f"{self.directory}:{os.environ['PATH']}",
                        "TMPDIR": str(self.directory),
                    },
                )

                self.assertEqual(1, result.returncode)
                self.assertEqual("existing\n", archive.read_text())
        self.assertFalse(calls.exists())

    def test_take_a_break_matches_the_window_pid_field(self) -> None:
        calls = self.directory / "wmctrl-calls"
        dialog_pid = self.directory / "dialog-pid"
        self.executable("zenity", 'printf "%s\\n" "$$" > "$DIALOG_PID"\n')
        self.executable(
            "wmctrl",
            'if [ "$1" = -l ]; then\n'
            '  pid=$(cat "$DIALOG_PID")\n'
            '  printf "0xwrong 0 999 host title-%s\\n" "$pid"\n'
            '  printf "0xright 0 %s host title\\n" "$pid"\n'
            "else\n"
            '  printf "%s\\n" "$*" > "$WMCTRL_CALLS"\n'
            "fi\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/take-a-break")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "DIALOG_PID": str(dialog_pid),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "WMCTRL_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("-i -r 0xright -b add,above\n", calls.read_text())

    def test_audio_action_survives_notification_failure(self) -> None:
        calls = self.directory / "cmus-calls"
        self.executable("cmus", "exit 0\n")
        self.executable("notify-send", "exit 1\n")
        self.executable("cmus-remote", 'printf "%s\\n" "$*" > "$CMUS_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/audio"), "toggle"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CMUS_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("--pause\n", calls.read_text())

    def test_ssid_preserves_spaces_from_machine_readable_output(self) -> None:
        calls = self.directory / "nmcli-calls"
        self.executable(
            "nmcli",
            'printf "%s\\n" "$*" > "$NMCLI_CALLS"\n'
            "printf 'no:Other Network\\nyes:Justice:of\\\\Toren\\n'\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/ssid")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "NMCLI_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("Justice:of\\Toren\n", result.stdout)
        self.assertEqual(
            "--terse --escape no --fields active,ssid device wifi\n",
            calls.read_text(),
        )

    def test_show_path_collapses_adjacent_duplicates(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin/show_path")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": "/usr/bin:/usr/bin:/bin"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("\n/usr/bin\n/bin\n\n", result.stdout)

    def test_pdf_optimize_propagates_ghostscript_failure(self) -> None:
        source = self.directory / "source.pdf"
        output = self.directory / "output.pdf"
        source.write_text("pdf\n")
        self.executable("file", "printf 'PDF document\\n'\n")
        self.executable("gs", "exit 42\n")

        result = subprocess.run(
            [str(ROOT / "bin/pdf-optimize"), str(source), str(output)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertEqual(42, result.returncode)
        self.assertFalse(output.exists())

    def test_fork_github_strips_page_url_suffixes(self) -> None:
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'if [ "$1" = clone ]; then mkdir "$4"; fi\n',
        )

        result = subprocess.run(
            [
                str(ROOT / "bin/fork-github"),
                "https://github.com/user/repository?tab=readme-ov-file",
            ],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "GIT_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "clone --filter=blob:none https://github.com/user/repository.git repository",
            calls.read_text().splitlines()[0],
        )

    def test_youtube_search_passes_only_search_terms(self) -> None:
        calls = self.directory / "ddg-calls"
        self.executable("ddg", 'printf "<%s>\\n" "$@" > "$DDG_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/youtube_search"), "tea", "ceremony"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "DDG": str(self.directory / "ddg"),
                "DDG_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "<site:youtube.com/playlist>\n<tea>\n<ceremony>\n",
            calls.read_text(),
        )

    def test_pre_commit_preserves_newlines_in_filenames(self) -> None:
        checkout = self.directory / "checkout"
        git_directory = self.directory / "git-directory"
        common_directory = self.directory / "common-directory"
        git_directory.mkdir()
        common_directory.mkdir()
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            f'  "rev-parse --git-dir") printf "%s\\n" "{git_directory}";;\n'
            f'  "rev-parse --git-common-dir") printf "%s\\n" "{common_directory}";;\n'
            '  "diff --name-only") printf "line\\nbreak\\0";;\n'
            '  "checkout-index "*) printf "<%s>\\n" "$4" > "$CHECKOUT";;\n'
            'esac\n',
        )
        self.executable(
            "xargs",
            'checker=\n'
            'for argument do [ ! -f "$argument" ] || checker=$argument; done\n'
            '[ -n "$checker" ] || exit 41\n'
            "cat >/dev/null\n",
        )

        result = subprocess.run(
            [os.path.relpath(ROOT / "config/githooks/pre-commit", self.directory)],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CHECKOUT": str(checkout),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("<line\nbreak>\n", checkout.read_text())

    def test_pre_commit_propagates_git_diff_failure(self) -> None:
        self.executable("git", "exit 23\n")

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(23, result.returncode)

    def test_pre_commit_checks_broken_symlinks(self) -> None:
        git_directory = self.directory / "git-directory"
        common_directory = self.directory / "common-directory"
        git_directory.mkdir()
        common_directory.mkdir()
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            f'  "rev-parse --git-dir") printf "%s\\n" "{git_directory}";;\n'
            f'  "rev-parse --git-common-dir") printf "%s\\n" "{common_directory}";;\n'
            '  "diff --name-only") printf "broken-link\\0";;\n'
            '  "checkout-index "*) prefix=${2#--prefix=}; ln -s missing "$prefix$4";;\n'
            'esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMPDIR": str(self.directory),
            },
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Broken symlink", result.stdout)

    def test_pre_commit_propagates_git_directory_query_failure(self) -> None:
        realpath_calls = self.directory / "realpath-calls"
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "diff --quiet") exit 1;;\n'
            '  "rev-parse --git-dir") exit 29;;\n'
            "esac\n",
        )
        self.executable(
            "realpath", 'printf "%s\\n" "$*" > "$REALPATH_CALLS"\nprintf "/wrong\\n"\n'
        )

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-commit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "REALPATH_CALLS": str(realpath_calls),
            },
        )

        self.assertEqual(29, result.returncode)
        self.assertFalse(realpath_calls.exists())

    def test_case_conflict_keeps_newlines_inside_filenames(self) -> None:
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "ls-files -z") printf "foo\\nbar\\0";;\n'
            '  "diff --staged") printf "FOO\\nbaz\\0";;\n'
            'esac\n',
        )

        result = subprocess.run(
            [
                "python3",
                str(
                    ROOT
                    / "config/githooks/pre_commit_hooks/check_case_conflict.py"
                ),
                "FOO\nbaz",
            ],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_pre_push_does_not_split_newlines_into_rust_filenames(self) -> None:
        calls = self.directory / "cargo-calls"
        (self.directory / "Cargo.toml").touch()
        self.executable("git", 'printf "fake.rs\\nnot-rust\\0"\n')
        self.executable("cargo", 'printf "%s\\n" "$*" > "$CARGO_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "CARGO_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(calls.exists())

    def test_pre_push_formats_rust_files_in_the_pushed_range(self) -> None:
        calls = self.directory / "calls"
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$CALLS"\n'
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{"a" * 40}\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", 'printf "cargo %s\\n" "$*" >> "$CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"diff --name-only -z --no-ext-diff {'b' * 40} {'a' * 40}\n"
            "rev-parse HEAD\n"
            "status --porcelain --untracked-files=all\n"
            "cargo fmt --check\n",
            calls.read_text(),
        )

    def test_pre_push_reads_every_ref_before_formatting(self) -> None:
        calls = self.directory / "calls"
        (self.directory / "Cargo.toml").touch()
        rust_sha = "c" * 40
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$CALLS"\n'
            'case "$1" in\n'
            f'  diff) [ "$6" != "{rust_sha}" ] || printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{rust_sha}\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", 'printf "cargo %s\\n" "$*" >> "$CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=(
                f"refs/heads/one {'a' * 40} refs/heads/one {'b' * 40}\n"
                f"refs/heads/two {rust_sha} refs/heads/two {'d' * 40}\n"
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {"CALLS": str(calls), "PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, calls.read_text().count("diff --name-only"))
        self.assertTrue(calls.read_text().endswith("cargo fmt --check\n"))

    def test_pre_push_rejects_rust_commit_that_is_not_checked_out(self) -> None:
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{"c" * 40}\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", "exit 99\n")

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("not checked out", result.stderr)

    def test_pre_push_rejects_dirty_rust_worktree(self) -> None:
        sha = "a" * 40
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{sha}\\n";;\n'
            '  status) printf "?? untracked.rs\\n";;\n'
            'esac\n',
        )
        self.executable("cargo", "exit 99\n")

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {sha} refs/heads/main {'b' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("dirty worktree", result.stderr)

    def test_pre_push_formats_jj_working_copy_commit(self) -> None:
        sha = "a" * 40
        calls = self.directory / "calls"
        (self.directory / "Cargo.toml").touch()
        self.executable(
            "git",
            'case "$1" in\n'
            '  diff) printf "src/lib.rs\\0";;\n'
            f'  rev-parse) printf "{"b" * 40}\\n";;\n'
            'esac\n',
        )
        self.executable("jj", f'printf "{sha}\\n"\n')
        self.executable("cargo", 'printf "%s\\n" "$*" > "$CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/githooks/pre-push")],
            cwd=self.directory,
            text=True,
            input=f"refs/heads/main {sha} refs/heads/main {'c' * 40}\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {"CALLS": str(calls), "PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("fmt --check\n", calls.read_text())

    def test_gh_comments_normalizes_url_and_rejects_unsafe_issue_names(self) -> None:
        calls = self.directory / "gh-calls"
        script_calls = self.directory / "script-calls"
        self.executable(
            "gh",
            'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
            "printf '{}\\n'\n",
        )
        self.executable("uname", "printf 'Darwin\\n'\n")
        self.executable(
            "script",
            'printf "%s\\n" "$*" > "$SCRIPT_CALLS"\nprintf \'issue output\\n\'\n',
        )
        self.executable("less", "exit 0\n")
        environment = os.environ | {
            "GH_CALLS": str(calls),
            "SCRIPT_CALLS": str(script_calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "github.com/user/repo/issues/123"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        unsafe = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "user/repo", "../escape"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("https://github.com/user/repo/issues/123", calls.read_text())
        self.assertEqual(
            "-q /dev/null gh issue view -c https://github.com/user/repo/issues/123\n",
            script_calls.read_text(),
        )
        self.assertEqual(1, unsafe.returncode)
        self.assertFalse((self.directory.parent / "escape.json").exists())

    def test_claude_statusline_rejects_invalid_workspace(self) -> None:
        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"cwd":"/directory/that/does/not/exist"}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)

    def test_claude_statusline_rejects_malformed_json(self) -> None:
        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input="not json",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_claude_statusline_finds_prompt_command_on_path(self) -> None:
        self.executable("prompt-command", 'printf "prompt from path\\n; "\n')

        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"model":{"display_name":"tea"}}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("prompt from path", result.stdout)

    def test_claude_statusline_propagates_prompt_command_failure(self) -> None:
        self.executable("prompt-command", "exit 23\n")

        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"model":{"display_name":"tea"}}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(23, result.returncode)
        self.assertEqual("", result.stdout)

    def test_claude_statusline_propagates_filter_failure(self) -> None:
        self.executable("prompt-command", 'printf "prompt\\n; "\n')
        self.executable("sed", "exit 24\n")

        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"model":{"display_name":"tea"}}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(24, result.returncode)
        self.assertEqual("", result.stdout)

    def test_attach_session_propagates_tmux_query_failures(self) -> None:
        self.executable(
            "tmux",
            'case "$1" in\n'
            "  show-option) exit 1;;\n"
            "  display-message) exit 23;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "config/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(23, result.returncode)

    def test_attach_session_propagates_session_listing_failure(self) -> None:
        self.executable(
            "tmux",
            'case "$1" in\n'
            "  show-option) exit 1;;\n"
            "  display-message)\n"
            '    case "$*" in\n'
            "      *client_last_session*) printf '\\n';;\n"
            "      *session_attached*) printf '1\\n';;\n"
            "    esac;;\n"
            "  list-sessions) exit 24;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "config/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(24, result.returncode)

    def test_attach_session_modes_do_not_run_session_queries(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable("tmux", 'printf "%s\\n" "$*" >> "$TMUX_CALLS"\n')
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "TMUX_CALLS": str(calls),
        }

        for mode in ("disable", "enable"):
            result = subprocess.run(
                [str(ROOT / "config/attach-session.sh"), mode],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(0, result.returncode, result.stderr)

        self.assertEqual(
            [
                "set-option -s @attach-session-disable 1",
                "set-option -su @attach-session-disable",
            ],
            calls.read_text().splitlines(),
        )

    def test_attach_session_does_not_switch_after_set_option_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'printf "%s\\n" "$*" >> "$TMUX_CALLS"\n'
            'case "$1 $2" in\n'
            "  \"show-option -sv\") exit 1;;\n"
            "  \"display-message -p\")\n"
            '    case "$*" in *client_last_session*) printf \'\\n\';; *) printf \'1\\n\';; esac;;\n'
            "  \"list-sessions -f\") printf '@2\\n';;\n"
            "  \"set-option destroy-unattached\") exit 25;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "config/attach-session.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(25, result.returncode)
        self.assertNotIn("switch-client", calls.read_text())

    def test_git_aliases_preserve_the_remote_default_when_deleting_merged_branches(self) -> None:
        repository = self.directory / "repository"
        remote = self.directory / "remote.git"
        repository.mkdir()
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repository,
            check=True,
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
        (repository / "file").write_text("tea\n")
        subprocess.run(["git", "add", "file"], cwd=repository, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "personal", str(remote)], cwd=repository, check=True)
        subprocess.run(
            ["git", "push", "personal", "HEAD:refs/heads/first", "HEAD:refs/heads/second"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "symbolic-ref",
                "refs/remotes/personal/HEAD",
                "refs/remotes/personal/first",
            ],
            cwd=repository,
            check=True,
        )
        config = f"include.path={ROOT / 'config/gitconfig'}"

        default_branch = subprocess.run(
            ["/usr/bin/git", "-c", config, "default-branch"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        delete_merged = subprocess.run(
            ["/usr/bin/git", "-c", config, "delete-merged"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        remaining = subprocess.run(
            ["git", "ls-remote", "--heads", str(remote)],
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        )
        branch_log = subprocess.run(
            ["/usr/bin/git", "-c", config, "branch-log"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        parent = subprocess.run(
            ["/usr/bin/git", "-c", config, "parent"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, default_branch.returncode)
        self.assertNotEqual(0, branch_log.returncode)
        self.assertNotEqual(0, parent.returncode)
        self.assertEqual(0, delete_merged.returncode, delete_merged.stderr)
        self.assertIn("refs/heads/first", remaining.stdout)
        self.assertNotIn("refs/heads/second", remaining.stdout)

    def test_jj_publish_passes_a_valid_update_to_the_pre_push_hook(self) -> None:
        publish = tomllib.loads((ROOT / "config/jj.toml").read_text())["aliases"][
            "publish"
        ]
        command = publish[-1]
        calls = self.directory / "jj-calls"
        hook_input = self.directory / "hook-input"
        commit = "a" * 40
        self.executable(
            "jj",
            'if [ "$1" = log ]; then\n'
            f'  printf "%s\\n" "{commit}"\n'
            "else\n"
            '  printf "%s\\n" "$*" >> "$JJ_CALLS"\n'
            "fi\n",
        )
        self.executable(
            "git",
            'if [ "$1 $2 $3" = "hook run pre-push" ]; then\n'
            '  cat > "$HOOK_INPUT"\n'
            "else\n"
            "  exit 99\n"
            "fi\n",
        )

        result = subprocess.run(
            ["/bin/bash", "-c", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "HOOK_INPUT": str(hook_input),
                "JJ_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        fields = hook_input.read_text().split()
        self.assertEqual(4, len(fields))
        self.assertEqual(commit, fields[1])
        self.assertEqual("0" * 40, fields[3])
        self.assertEqual(["tug", "push"], calls.read_text().splitlines())

    def test_git_autosquash_propagates_fallback_branch_failure(self) -> None:
        self.executable(
            "git",
            'case "$1" in\n'
            "  symbolic-ref) exit 1;;\n"
            "  for-each-ref) exit 24;;\n"
            "  *) exit 99;;\n"
            "esac\n",
        )

        result = subprocess.run(
            [str(ROOT / "bin/git-autosquash")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(24, result.returncode)


if __name__ == "__main__":
    unittest.main()
