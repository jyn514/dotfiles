import json
import os
from pathlib import Path
import select
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Callable
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


class CommandIntegrationTests(unittest.TestCase):
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
        self.executable("marked", 'cat "$3"\n')
        self.executable("dot", "cat\n")
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
        self.assertEqual([markdown.with_suffix(".preview.html"), dot.with_suffix(".preview.svg")], opened_paths)
        self.assertTrue(all(path.is_file() for path in opened_paths))
    def preview_environment(self) -> dict[str, str]:
        self.executable("marked", 'cat "$3"\n')
        self.executable("dot", "cat\n")
        # These only record the pathname: the consumer reads it after the launcher exits.
        for opener in ("open", "xdg-open"):
            self.executable(opener, 'printf "%s" "$1" > "$OPENED"\n')
        return os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
            "OPENED": str(self.directory / "opened"),
        }

    def run_preview(self, command: str, source: str | Path, environment: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin" / command), str(source)], cwd=self.directory,
            env=environment, capture_output=True, text=True,
        )

    def test_previews_persist_for_delayed_consumers_and_replace_only_final_extension(self) -> None:
        environment = self.preview_environment()
        for command, extension in (("view_dot", "svg"), ("view_markdown", "html")):
            for name, stem in (("雪 & notes.md", "雪 & notes"), ("plain", "plain"),
                               ("multi.part.dot", "multi.part"), (".hidden", ".hidden"),
                               ("-prefix.md", "-prefix")):
                for prefix in ("", "./", "dotted.dir/"):
                    with self.subTest(command=command, name=name, prefix=prefix):
                        source = self.directory / prefix / name
                        source.parent.mkdir(exist_ok=True)
                        source.write_text("first generation\n")
                        output = source.parent / f"{stem}.preview.{extension}"
                        result = self.run_preview(command, prefix + name, environment)
                        self.assertEqual(0, result.returncode, result.stderr)
                        opened = Path((self.directory / "opened").read_text())
                        if not opened.is_absolute():
                            opened = self.directory / opened
                        self.assertEqual(output, opened)
                        first = opened.read_text()  # Delayed consumer, not the opener.
                        self.assertIn("first generation", first)
                        source.write_text("second generation\n")
                        result = self.run_preview(command, prefix + name, environment)
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertIn("second generation", output.read_text())
                        self.assertNotIn("first generation", output.read_text())
                        self.assertEqual("second generation\n", source.read_text())
                        self.assertEqual([], list(source.parent.glob("*.tmp.*")))

    def test_previews_refuse_unowned_outputs_and_symlinks(self) -> None:
        environment = self.preview_environment()
        for command, extension in (("view_dot", "svg"), ("view_markdown", "html")):
            source = self.directory / "source.txt"
            source.write_text("source stays\n")
            output = self.directory / f"source.preview.{extension}"
            target = self.directory / "target"
            target.write_text("unrelated\n")
            for kind in ("regular", "directory", "symlink", "broken-symlink", "generated-symlink"):
                with self.subTest(command=command, kind=kind):
                    if kind == "regular":
                        output.write_text("unrelated\n")
                    elif kind == "directory":
                        output.mkdir()
                    else:
                        if kind == "generated-symlink":
                            target.write_text(f"<!-- Generated by dotfiles {command}; safe to replace. -->\n")
                        output.symlink_to(target if kind != "broken-symlink" else self.directory / "missing")
                    result = self.run_preview(command, source, environment)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("Refusing to overwrite non-preview", result.stderr)
                    self.assertFalse((self.directory / "opened").exists())
                    self.assertEqual("source stays\n", source.read_text())
                    if kind == "directory":
                        self.assertEqual([], list(output.iterdir()))
                        output.rmdir()
                    else:
                        if kind == "regular":
                            self.assertEqual("unrelated\n", output.read_text())
                        else:
                            self.assertTrue(output.is_symlink())
                        output.unlink()

    def test_failed_preview_generation_keeps_previous_output_and_opens_nothing(self) -> None:
        for command, extension, producers in (("view_dot", "svg", ("dot",)),
                                              ("view_markdown", "html", ("marked", "node"))):
            for producer in producers:
                with self.subTest(command=command, producer=producer):
                    environment = self.preview_environment()
                    source = self.directory / "source.txt"
                    source.write_text("complete\n")
                    output = source.with_suffix(f".preview.{extension}")
                    result = self.run_preview(command, source, environment)
                    self.assertEqual(0, result.returncode, result.stderr)
                    previous = output.read_bytes()
                    (self.directory / "opened").unlink()
                    self.executable(producer, "printf partial\nexit 23\n")
                    result = self.run_preview(command, source, environment)
                    self.assertEqual(23, result.returncode, result.stderr)
                    self.assertEqual(previous, output.read_bytes())
                    self.assertFalse((self.directory / "opened").exists())
                    self.assertEqual("complete\n", source.read_text())
                    self.assertEqual([], list(self.directory.glob("*.tmp.*")))
                    if producer == "node":
                        (self.directory / "node").unlink()

    def test_failed_opener_retains_complete_preview_and_source(self) -> None:
        environment = self.preview_environment()
        for command, extension, opener in (("view_dot", "svg", "xdg-open"),
                                            ("view_markdown", "html", "open")):
            with self.subTest(command=command):
                source = self.directory / "source.txt"
                source.write_text("first\n")
                self.assertEqual(0, self.run_preview(command, source, environment).returncode)
                self.executable(opener, "exit 29\n")
                source.write_text("second\n")
                result = self.run_preview(command, source, environment)
                self.assertEqual(29, result.returncode, result.stderr)
                self.assertIn("second", source.with_suffix(f".preview.{extension}").read_text())
                self.assertEqual("second\n", source.read_text())

    @unittest.skipUnless(shutil.which("dot"), "native Graphviz is required")
    def test_native_dot_preview_is_valid_svg_after_launcher_returns(self) -> None:
        from xml.etree import ElementTree

        environment = self.preview_environment()
        (self.directory / "dot").unlink()
        source = self.directory / "diagram.dot"
        source.write_text('digraph { a -> b [label="雪"]; }\n')
        result = self.run_preview("view_dot", source, environment)
        self.assertEqual(0, result.returncode, result.stderr)
        output = Path((self.directory / "opened").read_text())
        self.assertEqual("{http://www.w3.org/2000/svg}svg", ElementTree.parse(output).getroot().tag)

    def test_git_ignore_consumer_ignores_previews_but_not_sources(self) -> None:
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        sentinel = self.directory / "sentinel"
        subprocess.run(["git", "init", "--quiet", str(sentinel)], env=environment, check=True)
        (sentinel / "keep.txt").write_text("sentinel stays unchanged\n")
        (sentinel / ".git/info/exclude").write_text("*.md\n")
        before = {path.relative_to(sentinel): path.read_bytes() if path.is_file() else None
                  for path in sentinel.rglob("*")}

        repository = self.directory / "repository"
        repository.mkdir()
        files = ["diagram.preview.svg", "README.preview.html", "nested/x.preview.svg",
                 "diagram.dot", "README.md", "diagram.svg", "README.html"]
        # Ambient selectors must not redirect either native Git operation to another checkout.
        with patch.dict(os.environ, {"GIT_DIR": str(sentinel / ".git"), "GIT_WORK_TREE": str(sentinel)}):
            environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
            subprocess.run(["git", "init", "--quiet", str(repository)], env=environment, check=True)
            result = subprocess.run(
                ["git", "-c", f"core.excludesFile={ROOT / 'config/gitignore'}", "check-ignore", "--stdin"],
                input="\n".join(files) + "\n", cwd=repository, capture_output=True, text=True,
                env=environment,
            )
        self.assertTrue((repository / ".git").is_dir())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(files[:3], result.stdout.splitlines())
        after = {path.relative_to(sentinel): path.read_bytes() if path.is_file() else None
                 for path in sentinel.rglob("*")}
        self.assertEqual(before, after)

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

    def test_desktop_files_uses_custom_data_home_instead_of_default(self) -> None:
        home = self.directory / "home"
        custom = self.directory / "custom:data with spaces"
        first = self.directory / "first data"
        second = self.directory / "second data"
        for directory in (first, second, custom, home / ".local/share"):
            applications = directory / "applications"
            applications.mkdir(parents=True)
            (applications / "entry.desktop").touch()

        for suffix in ("", "/"):
            with self.subTest(trailing_slash=suffix):
                result = subprocess.run(
                    [str(ROOT / "bin/desktop-files")],
                    text=True,
                    capture_output=True,
                    env=os.environ | {
                        "HOME": str(home),
                        "XDG_DATA_HOME": str(custom) + suffix,
                        "XDG_DATA_DIRS": f"{first}:{second}",
                    },
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(
                    [
                        str(directory / "applications/entry.desktop")
                        for directory in (first, second, custom)
                    ],
                    result.stdout.splitlines(),
                )

    def test_desktop_files_defaults_unset_or_empty_data_home(self) -> None:
        home = self.directory / "home"
        data_home = home / ".local/share"
        applications = data_home / "applications"
        applications.mkdir(parents=True)
        entry = applications / "entry.desktop"
        entry.touch()

        for value in (None, "", str(data_home)):
            with self.subTest(data_home=value):
                environment = os.environ | {
                    "HOME": str(home),
                    "XDG_DATA_DIRS": str(self.directory / "missing system data"),
                }
                if value is None:
                    environment.pop("XDG_DATA_HOME", None)
                else:
                    environment["XDG_DATA_HOME"] = value
                result = subprocess.run(
                    [str(ROOT / "bin/desktop-files")],
                    text=True,
                    capture_output=True,
                    env=environment,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([str(entry)], result.stdout.splitlines())

    def merge_at_prompt(
        self,
        source: str | Path,
        destination: Path,
        before_reply: Callable[[], None],
        reply: str = "y\n",
    ) -> subprocess.CompletedProcess[str]:
        command = [str(ROOT / "bin/merge"), str(source), str(destination)]
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.directory,
        ) as process:
            try:
                output = b""
                while b"Remove old directory? y/[n] " not in output:
                    self.assertTrue(
                        select.select([process.stdout], [], [], 5)[0],
                        "merge did not reach its confirmation prompt",
                    )
                    chunk = os.read(process.stdout.fileno(), 4096)
                    self.assertTrue(chunk, "merge exited before its confirmation prompt")
                    output += chunk
                before_reply()
                remaining, error = process.communicate(reply.encode(), timeout=5)
                return subprocess.CompletedProcess(
                    command, process.returncode, (output + remaining).decode(), error.decode()
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_merge_refuses_removal_after_parent_symlink_retargets(self) -> None:
        first = self.directory / "A/source"
        replacement = self.directory / "B/source"
        destination = self.directory / "destination"
        for source, contents in ((first, "copied A\n"), (replacement, "uncopied B\n")):
            source.mkdir(parents=True)
            (source / "payload").write_text(contents)
        destination.mkdir()
        selected = self.directory / "selected"
        selected.symlink_to(first.parent, target_is_directory=True)

        def retarget() -> None:
            self.assertEqual("copied A\n", (destination / "payload").read_text())
            selected.unlink()
            selected.symlink_to(replacement.parent, target_is_directory=True)

        result = self.merge_at_prompt(selected / "source", destination, retarget)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Source retained", result.stderr)
        self.assertEqual("copied A\n", (first / "payload").read_text())
        self.assertEqual("uncopied B\n", (replacement / "payload").read_text())
        self.assertEqual("copied A\n", (destination / "payload").read_text())
        self.assertEqual(replacement, (selected / "source").resolve())

    def test_merge_refuses_removal_when_original_path_vanishes(self) -> None:
        source = self.directory / "source"
        moved = self.directory / "moved"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "payload").write_text("copied\n")

        def move_source() -> None:
            self.assertEqual("copied\n", (destination / "payload").read_text())
            source.rename(moved)

        result = self.merge_at_prompt(source, destination, move_source)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Source retained", result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual("copied\n", (moved / "payload").read_text())
        self.assertEqual("copied\n", (destination / "payload").read_text())

    def test_merge_unchanged_leaf_symlink_removes_only_link(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "payload").write_text("copied\n")
        selected = self.directory / "selected"
        selected.symlink_to(source, target_is_directory=True)

        result = self.merge_at_prompt(selected, destination, lambda: None)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(selected.is_symlink())
        self.assertEqual("copied\n", (source / "payload").read_text())
        self.assertEqual("copied\n", (destination / "payload").read_text())

    def test_merge_unchanged_ordinary_source_is_removed(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "payload").write_text("copied\n")

        result = self.merge_at_prompt(source, destination, lambda: None)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual("copied\n", (destination / "payload").read_text())

    def test_merge_does_not_revalidate_without_affirmative_confirmation(self) -> None:
        for index, (reply, status) in enumerate((("n\n", 0), ("\n", 0), ("", 1))):
            with self.subTest(reply=reply):
                source = self.directory / f"source-{index}"
                moved = self.directory / f"moved-{index}"
                destination = self.directory / f"destination-{index}"
                source.mkdir()
                destination.mkdir()
                (source / "payload").write_text("copied\n")

                def move_source() -> None:
                    self.assertEqual("copied\n", (destination / "payload").read_text())
                    source.rename(moved)

                result = self.merge_at_prompt(source, destination, move_source, reply)

                self.assertEqual(status, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)
                self.assertEqual("copied\n", (moved / "payload").read_text())
                self.assertEqual("copied\n", (destination / "payload").read_text())

    def test_merge_retains_source_after_copy_failure(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "payload").write_text("original\n")
        self.executable("cp", "exit 23\n")

        result = subprocess.run(
            [str(ROOT / "bin/merge"), str(source), str(destination)],
            text=True,
            input="y\n",
            capture_output=True,
            env=os.environ | {"PATH": f"{self.directory}:{os.environ['PATH']}"},
        )

        self.assertEqual(23, result.returncode, result.stderr)
        self.assertNotIn("Remove old directory?", result.stdout)
        self.assertEqual("original\n", (source / "payload").read_text())
        self.assertEqual([], list(destination.iterdir()))

    def test_merge_accepts_explicit_relative_dash_prefixed_operand(self) -> None:
        source = self.directory / "-source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "payload").write_text("copied\n")

        accepted = self.merge_at_prompt("./-source", destination, lambda: None)

        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertFalse(source.exists())
        self.assertEqual("copied\n", (destination / "payload").read_text())

    def test_merge_supports_plain_realpath_provider_without_flags(self) -> None:
        native_realpath = shutil.which("realpath")
        self.assertIsNotNone(native_realpath)
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "payload").write_text("copied\n")
        self.executable(
            "realpath",
            'case "$1" in -*) echo "unsupported realpath option" >&2; exit 64;; esac\n'
            'exec "$REALPATH_NATIVE" "$@"\n',
        )

        result = subprocess.run(
            [str(ROOT / "bin/merge"), str(source), str(destination)],
            text=True,
            input="y\n",
            capture_output=True,
            env=os.environ | {
                "PATH": f"{self.directory}:{os.environ['PATH']}",
                "REALPATH_NATIVE": native_realpath,
            },
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual("copied\n", (destination / "payload").read_text())

    def test_merge_copies_dotfiles_before_removing_source(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / ".hidden").write_text("kept\n")

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

    def test_merge_retained_files_are_independent(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        source_file = source / "note.txt"
        destination_file = destination / "note.txt"
        source_file.write_text("original\n")

        result = subprocess.run(
            [str(ROOT / "bin/merge"), str(source), str(destination)],
            text=True,
            input="\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(source.exists())
        source_identity = (source_file.stat().st_dev, source_file.stat().st_ino)
        destination_identity = (
            destination_file.stat().st_dev,
            destination_file.stat().st_ino,
        )
        self.assertNotEqual(source_identity, destination_identity)

        destination_file.write_text("changed through destination\n")
        self.assertEqual("original\n", source_file.read_text())

    def test_merge_retains_source_when_destination_entries_are_skipped(self) -> None:
        source = self.directory / "source"
        destination = self.directory / "destination"
        source.mkdir()
        destination.mkdir()
        (source / "collision").write_text("source\n")
        (destination / "collision").write_text("destination\n")
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


if __name__ == "__main__":
    unittest.main()
