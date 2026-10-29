import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class NativeClipboardTest(unittest.TestCase):
    BACKENDS = (
        ("xclip",),
        ("xsel",),
        ("wl-copy", "wl-paste"),
        ("pbcopy", "pbpaste"),
    )
    INPUT = b"input\n\n\0\xff"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.arguments = self.directory / "arguments.json"
        self.stdin = self.directory / "stdin"
        # Exclude host clipboard managers so each backend, including fallback
        # priority, is exercised independently of the machine running the suite.
        for name, target in (("basename", shutil.which("basename")),
                             ("python3", sys.executable)):
            self.assertIsNotNone(target)
            (self.directory / name).symlink_to(target)
        self.environment = os.environ | {
            "PATH": str(self.directory),
            "MOCK_ARGUMENTS": str(self.arguments),
            "MOCK_STDIN": str(self.stdin),
            "MOCK_STATUS": "0",
        }
        for name in ("a", "b", "glob-aa"):
            (self.directory / name).touch()

    def install_backends(self, first: int) -> None:
        for index, names in enumerate(self.BACKENDS):
            for name in names:
                path = self.directory / name
                path.unlink(missing_ok=True)
                if index >= first:
                    source = ROOT / "tests/copy/fixtures/native-backend.py"
                    subprocess.run(["cp", source, path], check=True)
                    subprocess.run(["cmp", source, path], check=True)
                    path.chmod(0o755)

    def run_native(
        self, mode: str, options: list[str], status: int = 0
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [str(ROOT / "bin" / mode), *options],
            check=False,
            input=self.INPUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.directory,
            env=self.environment | {"MOCK_STATUS": str(status)},
        )

    def assert_native(
        self, mode: str, backend: str, options: list[str], expected: list[str],
        status: int = 0,
    ) -> None:
        result = self.run_native(mode, options, status)
        self.assertEqual(status, result.returncode, result.stderr)
        self.assertEqual(b"", result.stderr)
        self.assertEqual(b"native output\n\n", result.stdout)
        self.assertEqual(
            {"backend": backend, "argv": expected},
            json.loads(self.arguments.read_text()),
        )
        self.assertEqual(self.INPUT, self.stdin.read_bytes())

    def test_native_argv_preserves_optional_flags_and_literal_types(self) -> None:
        # Check argv boundaries, not native parser acceptance (see xclip_test.py):
        # absent flags add no empty values, and the supplied type stays literal.
        # Include both a standalone matching glob and whitespace plus metacharacters.
        types = (None, "", "image/png", "text/plain; charset=utf-8", "*", "*?[ab]",
                 "image/png; charset=utf-8 * ? [ab]\tline\nbreak")
        for index, names in enumerate(self.BACKENDS):
            self.install_backends(index)
            supported_types = types if index in (0, 2) else (None,)
            for mode in ("copy", "paste"):
                backend = names[0] if mode == "copy" else names[-1]
                for primary in (False, True):
                    for mime in supported_types:
                        with self.subTest(backend=backend, mode=mode,
                                          primary=primary, mime=mime):
                            options = [] if mime is None else ["--type", mime]
                            if primary:
                                options.append("--primary")
                            selection = "primary" if primary else "clipboard"
                            if index == 0:
                                expected = ["-in" if mode == "copy" else "-out"]
                            elif index == 1:
                                expected = ["--input" if mode == "copy" else "--output"]
                            else:
                                expected = []
                            if mime is not None:
                                expected += ["-target" if index == 0 else "--type", mime]
                            if index == 0:
                                expected += ["-selection", selection]
                            elif index == 1:
                                expected += ["--" + selection]
                            elif index == 2 and primary:
                                expected += ["--primary"]
                            elif index == 3:
                                expected += ["-pboard", "find" if primary else "general"]
                            self.assert_native(mode, backend, options, expected)

    def test_native_exit_status_is_propagated_in_both_modes(self) -> None:
        for index, names in enumerate(self.BACKENDS):
            self.install_backends(index)
            for mode in ("copy", "paste"):
                backend = names[0] if mode == "copy" else names[-1]
                with self.subTest(backend=backend, mode=mode):
                    result = self.run_native(mode, [], status=37)
                    self.assertEqual(37, result.returncode, result.stderr)
                    self.assertEqual(backend, json.loads(self.arguments.read_text())["backend"])
                    self.assertEqual(self.INPUT, self.stdin.read_bytes())

    def test_unsupported_type_fails_without_invoking_native_backend(self) -> None:
        for index in (1, 3):
            self.install_backends(index)
            for mode in ("copy", "paste"):
                names = self.BACKENDS[index]
                backend = names[0] if mode == "copy" else names[-1]
                with self.subTest(backend=backend, mode=mode):
                    result = self.run_native(mode, ["--type", "image/png", "--primary"])
                    self.assertEqual(1, result.returncode)
                    self.assertEqual(f"{backend} doesn't support --type\n".encode(),
                                     result.stderr)
                    self.assertFalse(self.arguments.exists())
                    self.assertFalse(self.stdin.exists())


class ClipboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = os.environ | {
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }

    def executable(self, name: str, contents: str) -> Path:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)
        return path

    def run_command(
        self, command: list[str], **environment: str
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            command,
            check=False,
            input=b"input\n\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment | environment,
        )

    def test_terminal_selection_copy_removes_prompt_text(self) -> None:
        clipboard = self.directory / "clipboard"
        arguments = self.directory / "arguments"
        self.executable(
            "tmux",
            f'printf "%s\\n" "$@" > "{arguments}"\ncat > "{clipboard}"\n',
        )
        selection = (
            b"\x1b]133;A\x07\x1b[0;32m; \x1b[0;0mbuild"
            b"      \xe2\x8f\xb1 +1.25s [I]\n"
            b"ordinary output 12:34\n"
            b"binary \xff\n"
            b"\x1b[0;31m; \x1b[0;0mnext\t\xe2\x8f\xb1 21:45\r\n"
            b";\n"
        )

        result = subprocess.run(
            [str(ROOT / "bin/copy-terminal-selection"), "client-7"],
            check=False,
            input=selection,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["load-buffer", "-w", "-t", "client-7", "-"],
            arguments.read_text().splitlines(),
        )
        self.assertEqual(
            b"build\nordinary output 12:34\nbinary \xff\nnext\r\n\n",
            clipboard.read_bytes(),
        )

    def test_terminal_selection_copy_propagates_tmux_failure(self) -> None:
        self.executable("tmux", "cat >/dev/null\nexit 37\n")

        result = subprocess.run(
            [str(ROOT / "bin/copy-terminal-selection"), "client-7"],
            check=False,
            input=b"selection",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment,
        )

        self.assertEqual(37, result.returncode)

    def test_paste_primary_preserves_both_selections_exactly(self) -> None:
        first_copy = self.directory / "first-copy"
        second_copy = self.directory / "second-copy"
        self.executable(
            "paste",
            'if [ "${1:-}" = --primary ]; then\n'
            "    printf 'primary\\n\\n'\n"
            "else\n"
            "    printf 'clipboard\\n\\n'\n"
            "fi\n",
        )
        self.executable(
            "copy",
            'if [ -e "$FIRST_COPY" ]; then\n'
            '    cat > "$SECOND_COPY"\n'
            "else\n"
            '    cat > "$FIRST_COPY"\n'
            "fi\n",
        )
        for command in ("ydotool", "sleep"):
            self.executable(command, 'exit "${YDOTOOL_STATUS:-0}"\n')
        self.executable("logger", "cat >/dev/null\n")

        result = self.run_command(
            [str(ROOT / "bin/paste-primary")],
            FIRST_COPY=str(first_copy),
            SECOND_COPY=str(second_copy),
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"primary\n\n", first_copy.read_bytes())
        self.assertEqual(b"clipboard\n\n", second_copy.read_bytes())

    def test_paste_primary_restores_clipboard_and_returns_injection_failure(self) -> None:
        first_copy = self.directory / "first-copy"
        second_copy = self.directory / "second-copy"
        self.executable(
            "paste",
            'if [ "${1:-}" = --primary ]; then printf primary; else printf clipboard; fi\n',
        )
        self.executable(
            "copy",
            'if [ -e "$FIRST_COPY" ]; then cat > "$SECOND_COPY"; '
            'else cat > "$FIRST_COPY"; fi\n',
        )
        self.executable("ydotool", "exit 23\n")
        self.executable("sleep", "exit 0\n")
        self.executable("logger", "cat >/dev/null\n")

        result = self.run_command(
            [str(ROOT / "bin/paste-primary")],
            FIRST_COPY=str(first_copy),
            SECOND_COPY=str(second_copy),
        )

        self.assertEqual(23, result.returncode, result.stderr)
        self.assertEqual(b"primary", first_copy.read_bytes())
        self.assertEqual(b"clipboard", second_copy.read_bytes())

    def test_paste_primary_restores_clipboard_when_interrupted(self) -> None:
        first_copy = self.directory / "first-copy"
        second_copy = self.directory / "second-copy"
        self.executable(
            "paste",
            'if [ "${1:-}" = --primary ]; then printf primary; else printf clipboard; fi\n',
        )
        self.executable(
            "copy",
            'if [ -e "$FIRST_COPY" ]; then cat > "$SECOND_COPY"; '
            'else cat > "$FIRST_COPY"; fi\n',
        )
        self.executable("ydotool", 'kill -TERM "$PPID"\n')

        result = self.run_command(
            [str(ROOT / "bin/paste-primary")],
            FIRST_COPY=str(first_copy),
            SECOND_COPY=str(second_copy),
        )

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(b"primary", first_copy.read_bytes())
        self.assertEqual(b"clipboard", second_copy.read_bytes())


if __name__ == "__main__":
    unittest.main()
