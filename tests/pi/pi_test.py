#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin/pi"


class PiWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        sandbox = self.root / "codex-sandbox"
        sandbox.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        sandbox.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_wrapper(self, *arguments: str) -> list[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.root}:{environment['PATH']}"
        return subprocess.run(
            [str(WRAPPER), *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            env=environment,
        ).stdout.splitlines()

    def test_normal_session_delegates_to_sandbox(self) -> None:
        self.assertEqual(["prompt"], self.run_wrapper("prompt"))

    def test_one_shot_commands_remain_first_argument(self) -> None:
        for command in ("auth", "config", "install", "list", "remove", "uninstall", "update"):
            with self.subTest(command=command):
                self.assertEqual([command], self.run_wrapper(command))


if __name__ == "__main__":
    unittest.main()
