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

    def test_dragon_receives_one_raw_selection_through_stdin_adapter(self) -> None:
        calls = self.directory / "dragon-calls"
        self.executable("dragon", 'printf "%s\\0" "$@" > "$DRAGON_CALLS"\n')
        environment = os.environ | {
            "DRAGON_CALLS": str(calls),
            "PATH": f"{self.directory}:{os.environ['PATH']}",
        }
        payload = b"-path with spaces\ninvalid-\xff\n"
        result = subprocess.run(
            [str(ROOT / "libexec/tmux/with-selection.py"),
             str(ROOT / "libexec/tmux/dragon.sh")],
            input=payload, capture_output=True, env=environment,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"-x\0./" + payload + b"\0", calls.read_bytes())

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
        self.assertIn(b"dragon:", missing.stderr)


if __name__ == "__main__":
    unittest.main()
