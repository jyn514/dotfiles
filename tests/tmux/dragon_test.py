import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


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
                [str(ROOT / "libexec/tmux/dragon.sh"), argument],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(["-x", expected], calls.read_text().splitlines())

        result = subprocess.run(
            [str(ROOT / "libexec/tmux/dragon.sh"), "one", "two words"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["-x", "one", "two words"], calls.read_text().splitlines())

        for arguments in ([],):
            result = subprocess.run(
                [str(ROOT / "libexec/tmux/dragon.sh"), *arguments],
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
            [str(ROOT / "libexec/tmux/dragon.sh"), "--read0"],
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
                [str(ROOT / "libexec/tmux/dragon.sh"), "--read0"],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(2, malformed.returncode)
            self.assertFalse(calls.exists())

        for empty in (b"", b"\0"):
            cancelled = subprocess.run(
                [str(ROOT / "libexec/tmux/dragon.sh"), "--read0"],
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
            [str(ROOT / "libexec/tmux/dragon.sh"), "selection"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        dragon.unlink()
        missing = subprocess.run(
            [sys.executable, str(ROOT / "libexec/tmux/dragon.sh"), "selection"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": str(self.directory)},
        )

        self.assertEqual(37, failed.returncode)
        self.assertEqual(127, missing.returncode)
        self.assertEqual(b"dragon not found\n", missing.stderr)


if __name__ == "__main__":
    unittest.main()
