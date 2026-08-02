import os
from pathlib import Path
import subprocess
import tempfile
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
        source = repository / "file with spaces"
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
            "https://github.com/user/repo/blob/abc123/file%20with%20spaces#L1\n",
            matched.stdout,
            matched.stderr + calls.read_text(),
        )
        self.assertEqual(1, blank.returncode)
        self.assertEqual(
            "https://github.com/user/repo/blob/HEAD/file%20with%20spaces#L2\n",
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


if __name__ == "__main__":
    unittest.main()
