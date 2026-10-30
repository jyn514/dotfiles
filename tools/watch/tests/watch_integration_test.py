import json
import os
from pathlib import Path
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]


class CommandIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def executable(self, name: str, contents: str) -> None:
        path = self.directory / name
        path.write_text("#!/bin/sh\n" + contents)
        path.chmod(0o755)

    def test_real_runner_preserves_shell_status_and_watch_displays_it(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        for name in ("clear", "tput", "sleep"):
            (self.directory / name).symlink_to(fixtures / "terminal_command.py")
        environment = dict(os.environ)
        environment.pop("WATCH_RUNNER", None)
        environment["PATH"] = f"{self.directory}:{os.environ['PATH']}"

        # A real shell reports 128 + signal; ordinary exit 241 must stay 241.
        for case, expected in (("TERM", 143), ("INT", 130), ("0", 0), ("7", 7), ("241", 241)):
            with self.subTest(case=case):
                command = ["/bin/sh", str(fixtures / "native_status.sh"), "pty", case]
                direct = subprocess.run(
                    [str(ROOT / "libexec/runinpty.py"), *command],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(expected, direct.returncode, direct.stderr)
                self.assertEqual(b"native output\n", direct.stdout)
                watched = subprocess.run(
                    [str(ROOT / "bin/watch"), "-x", "/bin/sh", shlex.join(command)],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(31, watched.returncode, watched.stderr)
                annotation = f"\n[exit {expected}]".encode() if expected else b""
                self.assertEqual(b"native output" + annotation, watched.stdout)

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


if __name__ == "__main__":
    unittest.main()
