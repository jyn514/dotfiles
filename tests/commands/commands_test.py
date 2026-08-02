import json
import os
from pathlib import Path
import signal
import subprocess
import sys
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

    def test_dragon_wrapper_disambiguates_option_like_filenames(self) -> None:
        calls = self.directory / "dragon-calls"
        self.executable("dragon", 'printf "%s\\n" "$@" > "$DRAGON_CALLS"\n')
        environment = os.environ | {
            "DRAGON_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for argument, expected in (
            ("ordinary file", "ordinary file"),
            ("-option-like", "./-option-like"),
            ("https://example.invalid/file", "https://example.invalid/file"),
        ):
            result = subprocess.run(
                [str(ROOT / "config/dragon.sh"), argument],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["-x", expected], calls.read_text().splitlines())

        result = subprocess.run(
            [str(ROOT / "config/dragon.sh"), "one", "two words"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["-x", "one", "two words"], calls.read_text().splitlines())

        for arguments in ([],):
            result = subprocess.run(
                [str(ROOT / "config/dragon.sh"), *arguments],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(2, result.returncode)

    def test_dragon_wrapper_reads_validated_nul_selections_as_bytes(self) -> None:
        calls = self.directory / "dragon-calls"
        self.executable("dragon", 'printf "%s\\0" "$@" > "$DRAGON_CALLS"\n')
        environment = os.environ | {
            "DRAGON_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }
        payload = b"path with spaces\0line\nbreak\0-invalid-\xff\0"

        result = subprocess.run(
            [str(ROOT / "config/dragon.sh"), "--read0"],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            b"-x\0path with spaces\0line\nbreak\0./-invalid-\xff\0",
            calls.read_bytes(),
        )

        calls.unlink()
        for payload in (b"missing terminator", b"one\0\0"):
            malformed = subprocess.run(
                [str(ROOT / "config/dragon.sh"), "--read0"],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(2, malformed.returncode)
            self.assertFalse(calls.exists())

        for empty in (b"", b"\0"):
            cancelled = subprocess.run(
                [str(ROOT / "config/dragon.sh"), "--read0"],
                input=empty,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(0, cancelled.returncode, cancelled.stderr)
            self.assertFalse(calls.exists())

    def test_dragon_wrapper_propagates_launcher_failure(self) -> None:
        dragon = self.directory / "dragon"
        self.executable("dragon", "exit 37\n")
        environment = os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"}

        failed = subprocess.run(
            [str(ROOT / "config/dragon.sh"), "selection"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        dragon.unlink()
        missing = subprocess.run(
            [sys.executable, str(ROOT / "config/dragon.sh"), "selection"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": str(self.directory)},
        )

        self.assertEqual(37, failed.returncode)
        self.assertEqual(127, missing.returncode)
        self.assertEqual(b"dragon not found\n", missing.stderr)

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
            '  "ls-tree -r") printf "%s\\0" "$RELATIVE";;\n'
            '  "show "*) printf "unique line\\n\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "RELATIVE": source.name,
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
        self.assertEqual(1, sum(line.startswith("show abc123:") for line in call_lines))

    def test_remote_git_url_propagates_git_failures_and_rejects_unknown_hosts(self) -> None:
        repository = self.directory / "repository"
        repository.mkdir()
        source = repository / "file"
        source.write_text("unique line\n")
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "rev-parse --show-toplevel") printf "%s\\n" "$REPOSITORY";;\n'
            '  "remote get-url") printf "%s\\n" "$REMOTE_URL";;\n'
            '  "remote ") printf "origin\\n";;\n'
            '  "rev-list --remotes") [ "${REV_LIST_STATUS:-0}" -eq 0 ] || exit "$REV_LIST_STATUS"; printf "abc123\\n";;\n'
            '  "ls-tree -r") printf "%s\\0" "$RELATIVE";;\n'
            '  "show "*) exit "${SHOW_STATUS:-0}";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "RELATIVE": source.name,
            "REPOSITORY": str(repository),
            "REMOTE_URL": "https://github.com/user/repo.git",
            "REV_LIST_STATUS": "23",
        }

        failed_query = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        failed_grep = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"REV_LIST_STATUS": "0", "SHOW_STATUS": "24"},
        )
        unsupported = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment
            | {
                "REMOTE_URL": "https://codeberg.org/user/repo.git",
                "REV_LIST_STATUS": "0",
            },
        )

        self.assertEqual(23, failed_query.returncode)
        self.assertEqual("", failed_query.stdout)
        self.assertEqual(24, failed_grep.returncode)
        self.assertEqual("", failed_grep.stdout)
        self.assertEqual(2, unsupported.returncode)
        self.assertEqual("", unsupported.stdout)
        self.assertIn("unsupported upstream", unsupported.stderr)

    def test_remote_git_url_validates_ranges_before_running_git(self) -> None:
        source = self.directory / "file"
        source.write_text("one\ntwo\n")
        calls = self.directory / "git-calls"
        self.executable("git", 'touch "$GIT_CALLS"\nexit 99\n')
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for lines in (("expression",), ("0",), ("00",), ("2", "1")):
            result = subprocess.run(
                [str(ROOT / "bin/remote-git-url"), str(source), *lines],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(2, result.returncode, lines)
        self.assertFalse(calls.exists())

    def test_remote_git_url_propagates_remote_and_source_read_failures(self) -> None:
        repository = self.directory / "repository"
        repository.mkdir()
        source = repository / "file"
        source.write_text("line\n")
        self.executable(
            "git",
            'case "$1 $2" in\n'
            '  "rev-parse --show-toplevel") printf "%s\\n" "$REPOSITORY";;\n'
            '  "remote ") status=${REMOTE_STATUS:-23}; [ "$status" -eq 0 ] || exit "$status"; printf "origin\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "REPOSITORY": str(repository),
        }

        remote_failure = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        source.unlink()
        read_failure = subprocess.run(
            [str(ROOT / "bin/remote-git-url"), str(source), "1"],
            cwd=repository,
            env=environment | {"REMOTE_STATUS": "0"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(23, remote_failure.returncode)
        self.assertEqual(1, read_failure.returncode)
        self.assertIn("could not read", read_failure.stderr)

    def test_set_tmux_env_preserves_whitespace_and_equals(self) -> None:
        calls = self.directory / "tmux-calls"
        (self.directory / ".profile").write_text(
            "unset CARGO_HOME RUSTUP_HOME\n"
            "EDITOR='editor\n--wait'\n"
            "VISUAL=''\n"
            "PATH='/one path:/two=parts'\n"
            "export EDITOR VISUAL PATH\n"
        )
        self.executable(
            "tmux",
            'printf "%s\\0%s\\0%s\\0%s\\0%s\\0" '
            f'"$1" "$2" "$3" "$TMUX" "$TMUX_TMPDIR" >> "{calls}"\n',
        )

        result = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "HOME": str(self.directory),
                "TMUX": "socket value",
                "TMUX_TMPDIR": "/socket directory",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            b"set-environment\0EDITOR\0editor\n--wait\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0VISUAL\0\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0PATH\0/one path:/two=parts\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0-u\0CARGO_HOME\0"
            b"socket value\0/socket directory\0"
            b"set-environment\0-u\0RUSTUP_HOME\0"
            b"socket value\0/socket directory\0",
            calls.read_bytes(),
        )

    def test_set_tmux_env_preserves_unset_and_empty_tmux_context(self) -> None:
        calls = self.directory / "tmux-context"
        (self.directory / ".profile").write_text(
            "unset EDITOR VISUAL CARGO_HOME RUSTUP_HOME\n"
        )
        self.executable(
            "tmux",
            'if [ "${TMUX+x}" ]; then tmux="set:$TMUX"; else tmux=unset; fi\n'
            'if [ "${TMUX_TMPDIR+x}" ]; then tmp="set:$TMUX_TMPDIR"; else tmp=unset; fi\n'
            f'printf "%s %s\\n" "$tmux" "$tmp" >> "{calls}"\n',
        )
        environment = os.environ | {
            "HOME": str(self.directory),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "TMUX_CALLS": str(calls),
        }
        environment.pop("TMUX", None)
        environment.pop("TMUX_TMPDIR", None)

        unset = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        empty = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"TMUX": "", "TMUX_TMPDIR": ""},
        )

        self.assertEqual(0, unset.returncode, unset.stderr)
        self.assertEqual(0, empty.returncode, empty.stderr)
        self.assertEqual(
            ["unset unset"] * 5 + ["set: set:"] * 5,
            calls.read_text().splitlines(),
        )

    def test_set_tmux_env_stops_after_receiver_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        (self.directory / ".profile").write_text(
            "EDITOR=editor VISUAL=visual PATH=/profile/path\n"
            "export EDITOR VISUAL PATH\n"
            "unset CARGO_HOME RUSTUP_HOME\n"
        )
        self.executable(
            "tmux",
            f'printf "%s\\n" "$*" >> "{calls}"\n'
            '[ "$2" = VISUAL ] && exit 29\n'
            'exit 0\n',
        )

        result = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "HOME": str(self.directory),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(29, result.returncode)
        self.assertEqual(
            ["set-environment EDITOR editor", "set-environment VISUAL visual"],
            calls.read_text().splitlines(),
        )

    def test_set_tmux_env_propagates_profile_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        (self.directory / ".profile").write_text("return 17\n")
        self.executable("tmux", 'printf "%s\\n" "$*" > "$TMUX_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "config/set-tmux-env.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "HOME": str(self.directory),
                "TMUX_CALLS": str(calls),
            },
        )

        self.assertEqual(17, result.returncode)
        self.assertFalse(calls.exists())

    def test_tmux_cssh_uses_exact_window_names_and_labels_new_window_pane(self) -> None:
        calls = self.directory / "tmux-calls"
        created = self.directory / "window-created"
        self.executable(
            "tmux",
            'printf "<%s>\\n" "$@" >> "$TMUX_CALLS"\n'
            'case "$1" in\n'
            '  has-session) [ "$3" = current ];;\n'
            '  display-message) printf "current\\n";;\n'
            '  list-windows)\n'
            '    [ "${LIST_STATUS:-0}" -eq 0 ] || exit "$LIST_STATUS"\n'
            '    if [ -e "$WINDOW_CREATED" ]; then printf "cssh.-0\\n"; else printf "csshX-0\\n"; fi;;\n'
            '  new-window) touch "$WINDOW_CREATED"; printf "%%7\\n";;\n'
            '  split-window) printf "%%8\\n";;\n'
            'esac\n',
        )
        environment = os.environ | {
            "TMUX": "yes",
            "TMUX_CALLS": str(calls),
            "WINDOW_CREATED": str(created),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/tmux-cssh"), "-w", "-n", "cssh.", "first", "second"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        lines = calls.read_text().splitlines()
        self.assertIn("<%7>", lines)
        self.assertIn("<%8>", lines)
        pane_targets = [
            lines[index + 3]
            for index, line in enumerate(lines)
            if line == "<set-option>" and lines[index + 1] == "<-p>"
        ]
        self.assertEqual(["<%7>", "<%8>"], pane_targets)

    def test_tmux_cssh_propagates_window_query_failure(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'printf "%s\\n" "$*" >> "$TMUX_CALLS"\n'
            'case "$1" in\n'
            '  has-session) exit 1;;\n'
            '  display-message) printf "current\\n";;\n'
            '  list-windows) exit 26;;\n'
            'esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/tmux-cssh"), "-w", "host"],
            env=os.environ
            | {
                "TMUX_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(26, result.returncode)
        self.assertNotIn("new-window", calls.read_text())

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

    def test_renumber_tmux_sessions_restores_state_after_each_failure_or_signal(self) -> None:
        tmux = self.directory / "tmux"
        tmux.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, signal, sys\n"
            "state_path = os.environ['TMUX_STATE']\n"
            "count_path = os.environ['TMUX_COUNT']\n"
            "names = json.loads(open(state_path).read())\n"
            "if sys.argv[1] == 'list-sessions':\n"
            "    print('\\n'.join(names))\n"
            "    raise SystemExit(0)\n"
            "count = int(open(count_path).read()) + 1\n"
            "open(count_path, 'w').write(str(count))\n"
            "old, new = sys.argv[3:5]\n"
            "if old not in names or (new != old and new in names):\n"
            "    raise SystemExit(90)\n"
            "fail_at = {int(value) for value in os.environ.get('TMUX_FAIL_AT', '').split(',') if value}\n"
            "if count in fail_at:\n"
            "    raise SystemExit(27)\n"
            "names[names.index(old)] = new\n"
            "open(state_path, 'w').write(json.dumps(names))\n"
            "if count == int(os.environ.get('TMUX_SIGNAL_AT', '0')):\n"
            "    os.kill(os.getppid(), signal.SIGTERM)\n"
        )
        tmux.chmod(0o755)
        state = self.directory / "state"
        count = self.directory / "count"
        original = ["10", "named-session", "0", "2"]
        environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "TMUX_STATE": str(state),
            "TMUX_COUNT": str(count),
        }

        for fail_at in range(1, 7):
            with self.subTest(fail_at=fail_at):
                state.write_text(json.dumps(original))
                count.write_text("0")
                result = subprocess.run(
                    [str(ROOT / "config/renumber-tmux-sessions.sh")],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment | {"TMUX_FAIL_AT": str(fail_at)},
                )
                self.assertEqual(27, result.returncode, result.stderr)
                self.assertEqual(set(original), set(json.loads(state.read_text())))

        state.write_text(json.dumps(original))
        count.write_text("0")
        result = subprocess.run(
            [str(ROOT / "config/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"TMUX_SIGNAL_AT": "2"},
        )
        self.assertEqual(128 + signal.SIGTERM, result.returncode, result.stderr)
        self.assertEqual(set(original), set(json.loads(state.read_text())))

        state.write_text(json.dumps(original))
        count.write_text("0")
        result = subprocess.run(
            [str(ROOT / "config/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"1", "2", "3", "named-session"}, set(json.loads(state.read_text())))

        state.write_text(json.dumps(original))
        count.write_text("0")
        result = subprocess.run(
            [str(ROOT / "config/renumber-tmux-sessions.sh")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment | {"TMUX_FAIL_AT": "4,5"},
        )
        self.assertEqual(27, result.returncode)
        self.assertIn("during rollback", result.stderr)

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

    def test_makeuser_validates_arguments_before_privileged_commands(self) -> None:
        calls = self.directory / "adduser-calls"
        self.executable("adduser", 'touch "$ADDUSER_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/makeuser")],
            env=os.environ
            | {
                "ADDUSER_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)
        self.assertFalse(calls.exists())

    def test_clj_ignores_ambient_args_and_propagates_alias_query_failure(self) -> None:
        calls = self.directory / "clojure-calls"
        self.executable(
            "clojure",
            'if [ "$1 $2" = "-X:deps aliases" ]; then\n'
            '  [ -z "${QUERY_STATUS:-}" ] || exit "$QUERY_STATUS"\n'
            '  printf "%s\\n" "${ALIASES:-}"\n'
            'else\n'
            '  printf "<%s>\\n" "$@" > "$CLOJURE_CALLS"\n'
            'fi\n',
        )
        environment = os.environ | {
            "args": "ambient injected arguments",
            "CLOJURE_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        ordinary = subprocess.run(
            [str(ROOT / "bin/clj"), "user-argument"], env=environment, check=False
        )
        ordinary_calls = calls.read_text()
        calls.unlink()
        development = subprocess.run(
            [str(ROOT / "bin/clj")],
            env=environment | {"ALIASES": ":dev"},
            check=False,
        )
        development_calls = calls.read_text()
        calls.unlink()
        failed = subprocess.run(
            [str(ROOT / "bin/clj")],
            env=environment | {"QUERY_STATUS": "23"},
            check=False,
        )

        self.assertEqual(0, ordinary.returncode)
        self.assertNotIn("ambient", ordinary_calls)
        self.assertIn("<user-argument>", ordinary_calls)
        self.assertEqual(0, development.returncode)
        self.assertIn("<-A:dev>", development_calls)
        self.assertEqual(23, failed.returncode)
        self.assertFalse(calls.exists())

    def test_ansi_resets_background_without_debug_output(self) -> None:
        command = (
            f'source {ROOT / "bin/ansi"}; '
            "ansi::isAnsiSupported() { return 0; }; "
            "ansi --reset-background --no-restore tea"
        )
        result = subprocess.run(
            ["bash", "-c", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("\x1b[49mtea", result.stdout)
        self.assertNotIn("set | grep", (ROOT / "bin/ansi").read_text())

    def test_ssh_wrapper_cleans_up_agents_and_propagates_startup_failure(self) -> None:
        calls = self.directory / "ssh-wrapper-calls"
        self.executable(
            "ssh-add",
            'printf "ssh-add %s\\n" "$*" >> "$SSH_WRAPPER_CALLS"\n'
            'if [ "$1" = -l ] && [ ! -e "$AGENT_READY" ]; then exit 1; fi\n'
            'touch "$AGENT_READY"\n',
        )
        self.executable(
            "ssh-agent",
            'printf "ssh-agent %s\\n" "$*" >> "$SSH_WRAPPER_CALLS"\n'
            'if [ "$1" = -k ]; then exit 0; fi\n'
            '[ -z "${AGENT_STATUS:-}" ] || exit "$AGENT_STATUS"\n'
            'printf "SSH_AUTH_SOCK=/tmp/mock-agent; export SSH_AUTH_SOCK; SSH_AGENT_PID=123; export SSH_AGENT_PID;\\n"\n',
        )
        self.executable("systemctl", "exit 0\n")
        self.executable("ssh", "exit 17\n")
        environment = os.environ | {
            "AGENT_READY": str(self.directory / "agent-ready"),
            "SSH_WRAPPER_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        session = subprocess.run(
            [str(ROOT / "bin/ssh.sh"), "host"], env=environment, check=False
        )
        call_text = calls.read_text()
        calls.unlink()
        (self.directory / "agent-ready").unlink(missing_ok=True)
        startup_failure = subprocess.run(
            [str(ROOT / "bin/ssh.sh"), "host"],
            env=environment | {"AGENT_STATUS": "23"},
            check=False,
        )

        self.assertEqual(17, session.returncode)
        self.assertIn("ssh-agent -k", call_text)
        self.assertEqual(23, startup_failure.returncode)

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
        self.executable("which", "exit 99\n")
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

    def test_audio_media_action_requires_the_command_it_invokes(self) -> None:
        self.executable("cmus", "exit 0\n")

        result = subprocess.run(
            [str(ROOT / "bin/audio"), "play", "quiet"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": str(self.directory)},
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("no known media player", result.stderr)

    def test_audio_does_not_announce_a_failed_media_action(self) -> None:
        notifications = self.directory / "notifications"
        self.executable("cmus-remote", "exit 23\n")
        self.executable(
            "notify-send",
            'printf "%s\\n" "$*" > "$NOTIFICATIONS"\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/audio"), "next"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {
                "NOTIFICATIONS": str(notifications),
                "PATH": str(self.directory),
            },
        )

        self.assertEqual(23, result.returncode)
        self.assertFalse(notifications.exists())

    def test_hours_parses_meridiem_and_zero_pads_fractional_hours(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin/hours")],
            input="9:00AM-5:03PM\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("8.05\n", result.stdout)

    def test_groupme_transcript_reads_file_and_flushes_final_messages(self) -> None:
        transcript = self.directory / "groupme transcript"
        transcript.write_text("Avatar\nAlice\nFirst\n9:00 PM\nAvatar\nBob\nFinal\n")

        result = subprocess.run(
            [str(ROOT / "bin/groupme2transcript"), "--input", str(transcript)],
            input="Avatar\nWrong\nstdin\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("[][Alice]: First\n", result.stdout)
        self.assertIn("[9:00 PM][Bob]: Final\n", result.stdout)
        self.assertNotIn("Wrong", result.stdout)

    def test_pretty_parser_does_not_execute_input(self) -> None:
        marker = self.directory / "executed"
        malicious = f'__import__("pathlib").Path({str(marker)!r}).touch()'
        rejected = subprocess.run(
            [str(ROOT / "bin/pretty.py")],
            input=malicious + "\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        valid = subprocess.run(
            [str(ROOT / "bin/pretty.py")],
            input="[65, 66]\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(0, rejected.returncode)
        self.assertFalse(marker.exists())
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual("AB\n", valid.stdout)

    def test_watch_displays_failed_command_before_next_iteration(self) -> None:
        mocks = self.directory / "mocks"
        mocks.mkdir()
        runner = self.directory / "runinpty.py"
        runner.write_text("#!/bin/sh\nprintf 'failed output'\nexit 7\n")
        runner.chmod(0o755)
        for name, contents in (
            ("clear", "exit 0\n"),
            ("tput", "exit 0\n"),
            ("sleep", "exit 31\n"),
        ):
            executable = mocks / name
            executable.write_text("#!/bin/sh\n" + contents)
            executable.chmod(0o755)

        result = subprocess.run(
            [str(ROOT / "bin/watch"), "command"],
            env=os.environ
            | {
                "PATH": f"{mocks}:{os.environ['PATH']}",
                "WATCH_RUNNER": str(runner),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(31, result.returncode)
        self.assertEqual("failed output\n[exit 7]", result.stdout)

    def test_archive_webpage_rejects_path_titles_and_serializes_metadata(self) -> None:
        archive = (ROOT / "bin/archive-webpage").read_text()

        self.assertIn('page_title === "." || page_title === ".."', archive)
        self.assertIn('/[\\/\\\\]/.test(page_title)', archive)
        self.assertIn("JSON.stringify({", archive)
        self.assertNotIn("'\"title\": \"' + page.title", archive)

    def test_callgraph_stops_at_each_failed_producer(self) -> None:
        self.executable(
            "valgrind",
            '[ "${FAIL_STAGE:-}" = valgrind ] && exit 23\nprintf "valgrind\\n" >> "$CALLS"\n',
        )
        self.executable(
            "gprof2dot",
            '[ "${FAIL_STAGE:-}" = gprof2dot ] && exit 24\nprintf "gprof2dot\\n" >> "$CALLS"\nprintf "digraph {}\\n"\n',
        )
        self.executable(
            "dot",
            '[ "${FAIL_STAGE:-}" = dot ] && exit 25\nprintf "dot\\n" >> "$CALLS"\nprintf "png\\n"\n',
        )
        calls = self.directory / "calls"
        environment = os.environ | {
            "CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        for stage, expected in (("valgrind", 23), ("gprof2dot", 24), ("dot", 25)):
            calls.unlink(missing_ok=True)
            result = subprocess.run(
                [str(ROOT / "bin/callgraph"), "program"],
                cwd=self.directory,
                env=environment | {"FAIL_STAGE": stage},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(expected, result.returncode, stage)
            self.assertNotIn("generated callgraph", result.stdout)

    def test_callgraph_comparison_stops_before_diff_on_read_failure(self) -> None:
        marker = self.directory / "diff-called"
        self.executable("diff", f"touch {marker}\n")

        result = subprocess.run(
            [str(ROOT / "bin/callgraph-cmp"), "missing.dot", "second.dot"],
            cwd=self.directory,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertFalse(marker.exists())

    def test_callgraph_comparison_accepts_graphs_without_edges(self) -> None:
        (self.directory / "first.dot").write_text("digraph {}\n")
        (self.directory / "second.dot").write_text("digraph {}\n")

        result = subprocess.run(
            [str(ROOT / "bin/callgraph-cmp"), "first.dot", "second.dot"],
            cwd=self.directory,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_usage_propagates_du_failure_without_sorting(self) -> None:
        marker = self.directory / "sort-called"
        self.executable("du", "exit 27\n")
        self.executable("sort", f"touch {marker}\n")

        result = subprocess.run(
            [str(ROOT / "bin/usage"), str(self.directory)],
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(27, result.returncode)
        self.assertFalse(marker.exists())

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

    def test_ssid_propagates_nmcli_failure(self) -> None:
        self.executable("nmcli", "exit 27\n")

        result = subprocess.run(
            [str(ROOT / "bin/ssid")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(27, result.returncode)
        self.assertEqual("", result.stdout)

    def test_toggle_dnd_does_not_mutate_state_after_query_failure(self) -> None:
        calls = self.directory / "gsettings-calls"
        self.executable(
            "gsettings",
            'printf "%s\\n" "$*" >> "$GSETTINGS_CALLS"\n'
            'case "$1" in get) exit 29;; esac\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/toggle-dnd")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "GSETTINGS_CALLS": str(calls),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(29, result.returncode)
        self.assertEqual(
            "get org.gnome.desktop.notifications show-banners\n",
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

    def test_fork_github_keeps_repository_name_when_checkout_directory_differs(self) -> None:
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "<%s>\\n" "$@" >> "$GIT_CALLS"\n'
            'if [ "$1" = clone ]; then mkdir "$4"; fi\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [str(ROOT / "bin/fork-github"), "owner/repository", "custom checkout"],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        missing = subprocess.run(
            [str(ROOT / "bin/fork-github")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("custom checkout\n", result.stdout)
        self.assertEqual(
            ["<remote>", "<add>", "<origin>", "<git@github.com:jyn514/repository.git>"],
            calls.read_text().splitlines()[-4:],
        )
        self.assertEqual(2, missing.returncode)
        self.assertIn("usage:", missing.stderr)

    def test_b_enters_workspace_and_preserves_metadata_failures(self) -> None:
        workspace = self.directory / "workspace with spaces"
        workspace.mkdir()
        bacon_cwd = self.directory / "bacon-cwd"
        self.executable(
            "cargo",
            'if [ -n "${CARGO_STATUS:-}" ]; then exit "$CARGO_STATUS"; fi\n'
            'printf \'{"workspace_root":"%s"}\\n\' "$WORKSPACE"\n',
        )
        self.executable(
            "jq",
            'if [ -n "${JQ_STATUS:-}" ]; then exit "$JQ_STATUS"; fi\n'
            "python3 -c 'import json, sys; print(json.load(sys.stdin)[\"workspace_root\"])'\n",
        )
        self.executable("bacon", 'pwd > "$BACON_CWD"\n')
        environment = os.environ | {
            "BACON_CWD": str(bacon_cwd),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "WORKSPACE": str(workspace),
        }

        success = subprocess.run([str(ROOT / "bin/b")], env=environment, check=False)
        cargo_failure = subprocess.run(
            [str(ROOT / "bin/b")], env=environment | {"CARGO_STATUS": "23"}, check=False
        )
        jq_failure = subprocess.run(
            [str(ROOT / "bin/b")], env=environment | {"JQ_STATUS": "24"}, check=False
        )

        self.assertEqual(0, success.returncode)
        self.assertEqual(f"{workspace}\n", bacon_cwd.read_text())
        self.assertEqual(23, cargo_failure.returncode)
        self.assertEqual(24, jq_failure.returncode)

    def test_bandit_preserves_spaces_and_hyphens_in_password(self) -> None:
        calls = self.directory / "sshpass-calls"
        (self.directory / "bandit.txt").write_text("7 - tea time-with-hyphens\n")
        self.executable("sshpass", 'printf "<%s>\\n" "$@" > "$SSHPASS_CALLS"\n')

        result = subprocess.run(
            [str(ROOT / "bin/bandit")],
            cwd=self.directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "SSHPASS_CALLS": str(calls),
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "<-p>\n<tea time-with-hyphens>\n<ssh>\n<-p>\n<2220>\n"
            "<bandit7@bandit.labs.overthewire.org>\n",
            calls.read_text(),
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

    def test_pre_commit_rejects_malformed_xml(self) -> None:
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
            '  "diff --name-only") printf "broken.xml\\0";;\n'
            '  "checkout-index "*) prefix=${2#--prefix=}; printf "<open>\\n" > "$prefix$4";;\n'
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
        self.assertIn("Failed to xml parse", result.stdout)

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
        self.executable(
            "gh",
            'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
            'case " $* " in *" --json "*) printf \'{}\\n\';; '
            "*) printf 'issue output\\n';; esac\n",
        )
        self.executable("less", 'exit "${LESS_STATUS:-0}"\n')
        environment = os.environ | {
            "GH_CALLS": str(calls),
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
        self.assertEqual(2, len(calls.read_text().splitlines()))
        self.assertEqual(1, unsafe.returncode)
        self.assertFalse((self.directory.parent / "escape.json").exists())

    def test_gh_comments_does_not_publish_partial_exports(self) -> None:
        self.executable(
            "gh",
            'case " $* " in\n'
            '  *" --json "*) printf "json\\n"; '
            '[ -z "${GH_STATUS:-}" ] || exit "$GH_STATUS";;\n'
            '  *) printf "text\\n"; '
            '[ -z "${TEXT_STATUS:-}" ] || exit "$TEXT_STATUS";;\n'
            "esac\n",
        )
        self.executable("less", 'exit "${LESS_STATUS:-0}"\n')
        environment = os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"}

        for variable, status in (("GH_STATUS", 24), ("TEXT_STATUS", 25)):
            result = subprocess.run(
                [str(ROOT / "bin/gh-comments"), "user/repo", "123"],
                cwd=self.directory,
                env=environment | {variable: str(status)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(status, result.returncode, variable)
            self.assertFalse((self.directory / "123.json").exists())
            self.assertFalse((self.directory / "123.txt").exists())
            self.assertEqual([], list(self.directory.glob(".123.*")))

        less_failure = subprocess.run(
            [str(ROOT / "bin/gh-comments"), "user/repo", "123"],
            cwd=self.directory,
            env=environment | {"LESS_STATUS": "26"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(26, less_failure.returncode)
        self.assertEqual("json\n", (self.directory / "123.json").read_text())
        self.assertEqual("text\n", (self.directory / "123.txt").read_text())

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

    def test_claude_statusline_uses_resolved_renderer_not_path(self) -> None:
        marker = self.directory / "path-renderer-called"
        self.executable("prompt-command", f'touch "{marker}"\nexit 99\n')
        workspace = self.directory / "workspace"
        workspace.mkdir()
        installed = self.directory / "statusline-command.sh"
        installed.symlink_to(ROOT / "config/claude-statusline.sh")

        result = subprocess.run(
            [str(installed)],
            text=True,
            input=(
                '{"workspace":{"current_dir":'
                + json.dumps(str(workspace))
                + '},"model":{"display_name":"tea"},'
                '"context_window":{"used_percentage":42.4}}'
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ
            | {
                "HOME": str(self.directory),
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "container": "fixture",
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith(" ctx:42% (tea@fixture"), result.stdout)
        self.assertTrue(result.stdout.endswith(") ~/workspace"), result.stdout)
        self.assertFalse(marker.exists())

    def test_claude_statusline_rejects_invalid_model_without_partial_output(self) -> None:
        result = subprocess.run(
            [str(ROOT / "config/claude-statusline.sh")],
            text=True,
            input='{"model":{"display_name":42}}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("model name must be a string", result.stderr)

    def test_claude_statusline_contains_no_json_or_shell_filters(self) -> None:
        launcher = (ROOT / "config/claude-statusline.sh").read_text()

        self.assertIn('os.execv(command, [str(command), "claude"])', launcher)
        for old_filter in ("jq -r", "head -n", "tr -d", "input=$(cat)", "command -v"):
            self.assertNotIn(old_filter, launcher)

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

    def test_attach_session_selects_first_detached_session_with_exact_arguments(self) -> None:
        calls = self.directory / "tmux-calls"
        self.executable(
            "tmux",
            'printf "<%s>" "$1" >> "$TMUX_CALLS"\n'
            'shift\n'
            'printf " <%s>" "$@" >> "$TMUX_CALLS"\n'
            'printf "\\n" >> "$TMUX_CALLS"\n'
            'case "$(tail -n 1 "$TMUX_CALLS")" in\n'
            '  "<show-option> <-sv> <@attach-session-disable>") exit 1;;\n'
            '  "<list-sessions> <-f> <#{?session_attached,0,1}> <-F> <#{session_id}>")\n'
            "    printf '@9\\n@12\\n';;\n"
            '  *client_last_session*) printf \'\\n\';;\n'
            '  *session_attached*) printf \'1\\n\';;\n'
            'esac\n',
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

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "<show-option> <-sv> <@attach-session-disable>",
                "<display-message> <-p> <#{client_last_session}>",
                "<display-message> <-p> <#{session_attached}>",
                "<list-sessions> <-f> <#{?session_attached,0,1}> <-F> <#{session_id}>",
                "<set-option> <destroy-unattached>",
                "<switch-client> <-t> <@9>",
            ],
            calls.read_text().splitlines(),
        )

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
            [
                "git",
                "push",
                "personal",
                "HEAD:refs/heads/first",
                "HEAD:refs/heads/second",
                "HEAD:refs/heads/-option-like",
            ],
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
        self.assertNotIn("refs/heads/-option-like", remaining.stdout)

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

    def test_jj_push_bookmark_sanitizes_conventional_commit_subjects(self) -> None:
        template = tomllib.loads((ROOT / "config/jj.toml").read_text())["templates"][
            "git_push_bookmark"
        ]
        expression = template.replace("description", '"Fix: parser"', 1)

        rendered = subprocess.run(
            ["jj", "log", "--no-graph", "-r", "@", "-T", expression],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, rendered.returncode, rendered.stderr)
        bookmark = rendered.stdout
        self.assertEqual("jyn/Fix-", bookmark)
        valid = subprocess.run(
            ["git", "check-ref-format", f"refs/heads/{bookmark}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, valid.returncode, valid.stderr)

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

    def test_git_autosquash_only_defaults_remote_for_a_missing_config_key(self) -> None:
        calls = self.directory / "git-calls"
        self.executable(
            "git",
            'printf "%s\\n" "$*" >> "$GIT_CALLS"\n'
            'case "$1" in\n'
            '  symbolic-ref) printf "main\\n";;\n'
            '  config) exit "${CONFIG_STATUS:-1}";;\n'
            '  merge-base) printf "abc123\\n";;\n'
            '  revise) exit 0;;\n'
            'esac\n',
        )
        environment = os.environ | {
            "GIT_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

        missing = subprocess.run(
            [str(ROOT / "bin/git-autosquash")], env=environment, check=False
        )
        fatal = subprocess.run(
            [str(ROOT / "bin/git-autosquash")],
            env=environment | {"CONFIG_STATUS": "25"},
            check=False,
        )

        self.assertEqual(0, missing.returncode)
        self.assertIn("merge-base HEAD origin/HEAD", calls.read_text().splitlines())
        self.assertEqual(25, fatal.returncode)


if __name__ == "__main__":
    unittest.main()
