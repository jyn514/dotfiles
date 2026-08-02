import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


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

    def test_xclip_receives_type_and_primary_selection(self) -> None:
        arguments = self.directory / "arguments"
        stdin = self.directory / "stdin"
        self.executable(
            "xclip",
            'printf "%s\\n" "$@" > "$MOCK_ARGUMENTS"\n'
            'cat > "$MOCK_STDIN"\n',
        )

        result = self.run_command(
            [str(ROOT / "bin/copy"), "--type", "image/png", "--primary"],
            MOCK_ARGUMENTS=str(arguments),
            MOCK_STDIN=str(stdin),
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["-in", "--type", "image/png", "-selection", "primary"],
            arguments.read_text().splitlines(),
        )
        self.assertEqual(b"input\n\n", stdin.read_bytes())

    def test_xsel_uses_clipboard_option(self) -> None:
        arguments = self.directory / "arguments"
        self.executable(
            "xsel",
            'printf "%s\\n" "$@" > "$MOCK_ARGUMENTS"\n'
            'cat >/dev/null\n',
        )

        result = self.run_command(
            [str(ROOT / "bin/copy")],
            MOCK_ARGUMENTS=str(arguments),
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["--input", "--clipboard"], arguments.read_text().splitlines())

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
