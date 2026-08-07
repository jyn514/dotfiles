import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/shell-data"))
from shell_data.abbreviations import Entry, validate  # noqa: E402


VALID_DATA = """# comment

:q=exit
equal=printf a=b=c
quoted=printf '$HOME' "two words"
pipeline=first | second && third
-dash=-n
unicode=界 café
"""


class AbbreviationGrammarTest(unittest.TestCase):
    def test_valid_grammar_preserves_first_equals_and_literal_text(self) -> None:
        entries, diagnostics = validate(VALID_DATA.encode())

        self.assertEqual([], diagnostics)
        self.assertEqual(
            [
                Entry(":q", "exit", 3),
                Entry("equal", "printf a=b=c", 4),
                Entry("quoted", "printf '$HOME' \"two words\"", 5),
                Entry("pipeline", "first | second && third", 6),
                Entry("-dash", "-n", 7),
                Entry("unicode", "界 café", 8),
            ],
            entries,
        )

    def test_reports_every_malformed_and_duplicate_line(self) -> None:
        contents = (
            b"=empty-name\n"
            b"empty-expansion=\n"
            b"white space=value\n"
            b"missing-separator\n"
            b"duplicate=one\n"
            b"duplicate=two\n"
            b"nul=bad\0value\n"
            b"carriage=bad\rmiddle\n"
            b"invalid=\xff\n"
        )

        _entries, diagnostics = validate(contents)

        self.assertEqual(
            [
                "line 1: name must not be empty",
                "line 2: expansion must not be empty",
                "line 3: name must not contain whitespace",
                "line 4: expected name=expansion",
                "line 6: duplicate name 'duplicate'; first defined on line 5",
                "line 7: NUL is not allowed",
                "line 8: carriage return is only allowed in CRLF",
                "line 9: line is not valid UTF-8",
            ],
            [str(diagnostic) for diagnostic in diagnostics],
        )

    def test_crlf_and_final_line_without_newline_are_valid(self) -> None:
        entries, diagnostics = validate(b"one=first\r\ntwo=second")

        self.assertEqual([], diagnostics)
        self.assertEqual(["one", "two"], [entry.name for entry in entries])

    def test_cli_validates_default_repository_file(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/shell-data/main.py")],
            cwd=Path("/"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"", result.stdout)

    def test_cli_reports_path_line_and_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "abbr.txt"
            invalid.write_text("same=one\nsame=two\n")
            malformed = subprocess.run(
                [sys.executable, str(ROOT / "tools/shell-data/main.py"), str(invalid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            missing = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/shell-data/main.py"),
                    str(Path(temporary) / "missing"),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(1, malformed.returncode)
        self.assertIn(f"{invalid}:line 2: duplicate name 'same'".encode(), malformed.stderr)
        self.assertEqual(1, missing.returncode)
        self.assertIn(b"missing", missing.stderr)


class NativeLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dotfiles = Path(self.temporary.name)
        library = self.dotfiles / "lib"
        library.mkdir()
        self.abbreviations = library / "abbr.txt"
        self.abbreviations.write_text(
            "equal=printf a=b=c\n"
            "syntax=printf '$HOME' | next && done\n"
            "-dash=-n two words\n"
            "backslash=printf C:\\tmp\\file\n"
            "unicode=界 café\n"
        )

    def profile_loader(self) -> str:
        profile = (ROOT / "config/profile").read_text()
        start = profile.index("_load_aliases() {")
        end = profile.index("\n}\n", start) + 2
        return profile[start:end]

    def test_posix_loader_registers_each_expansion_as_one_literal_argument(self) -> None:
        script = (
            self.profile_loader()
            + "\nalias() { printf '%s\\0' \"$@\"; }\n"
            + "_load_aliases\n"
        )

        shells = ["/bin/sh"]
        for candidate in (shutil.which("bash"), shutil.which("zsh")):
            if candidate:
                shells.append(candidate)
        for shell in shells:
            with self.subTest(shell=shell):
                result = subprocess.run(
                    [shell, "-c", script],
                    env=os.environ | {"DOTFILES": str(self.dotfiles)},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(
                    [
                        b"equal=printf a=b=c",
                        b"syntax=printf '$HOME' | next && done",
                        b"-dash=-n two words",
                        b"backslash=printf C:\\tmp\\file",
                        "unicode=界 café".encode(),
                    ],
                    result.stdout.rstrip(b"\0").split(b"\0"),
                )

    def test_posix_loader_propagates_read_and_registration_failures(self) -> None:
        definition = self.profile_loader()
        registration = subprocess.run(
            ["/bin/sh", "-c", definition + "\nalias() { return 29; }\n_load_aliases"],
            env=os.environ | {"DOTFILES": str(self.dotfiles)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.abbreviations.unlink()
        read = subprocess.run(
            ["/bin/sh", "-c", definition + "\n_load_aliases"],
            env=os.environ | {"DOTFILES": str(self.dotfiles)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(29, registration.returncode)
        self.assertNotEqual(0, read.returncode)

    @unittest.skipUnless(shutil.which("fish"), "fish is unavailable")
    def test_fish_loader_registers_expansions_as_literal_arguments(self) -> None:
        fish_config = (ROOT / "config/config.fish").read_text()
        start = fish_config.index("# load common aliases")
        end = fish_config.index("set --erase abbreviations", start) + len(
            "set --erase abbreviations"
        )
        loader = fish_config[start:end]
        script = (
            "function abbr\n"
            "  for argument in $argv\n"
            "    printf '%s\\0' \"$argument\"\n"
            "  end\n"
            "end\n"
            "function load_abbreviations\n"
            f"{loader}\n"
            "end\n"
            "load_abbreviations\n"
        )

        result = subprocess.run(
            ["fish", "--no-config", "-c", script],
            env=os.environ | {"DOTFILES": str(self.dotfiles)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        arguments = result.stdout.rstrip(b"\0").split(b"\0")
        self.assertEqual(
            [
                b"--add",
                b"--global",
                b"equal",
                b"printf a=b=c",
                b"--add",
                b"--global",
                b"syntax",
                b"printf '$HOME' | next && done",
            ],
            arguments[:8],
        )
        backslash = arguments.index(b"backslash")
        self.assertEqual(b"printf C:\\tmp\\file", arguments[backslash + 1])

    @unittest.skipUnless(shutil.which("fish"), "fish is unavailable")
    def test_fish_loader_propagates_registration_failure(self) -> None:
        fish_config = (ROOT / "config/config.fish").read_text()
        start = fish_config.index("# load common aliases")
        end = fish_config.index("set --erase abbreviations", start) + len(
            "set --erase abbreviations"
        )
        loader = fish_config[start:end]
        script = (
            "function abbr\n"
            "  return 31\n"
            "end\n"
            "function load_abbreviations\n"
            f"{loader}\n"
            "end\n"
            "load_abbreviations\n"
        )

        result = subprocess.run(
            ["fish", "--no-config", "-c", script],
            env=os.environ | {"DOTFILES": str(self.dotfiles)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(31, result.returncode)


if __name__ == "__main__":
    unittest.main()
