#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin/pi"
LOCKFILE = ROOT / "tools/pi-npm/package-lock.json"


class PiWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        lock_hash = subprocess.run(
            ["git", "-C", str(ROOT), "hash-object", str(LOCKFILE)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        install = self.root / "dotfiles/pi-npm" / lock_hash / "node_modules"
        adapter = install / "pi-mcp-adapter"
        adapter.mkdir(parents=True)
        (adapter / "index.ts").touch()
        (adapter / "skills").mkdir()
        binary = install / ".bin/pi"
        binary.parent.mkdir()
        binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nprintf "JJ_AGENT=%s\\n" "$JJ_AGENT"\n')
        binary.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_wrapper(self, *arguments: str) -> list[str]:
        environment = os.environ.copy()
        environment["XDG_CACHE_HOME"] = str(self.root)
        return subprocess.run(
            [str(WRAPPER), *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            env=environment,
        ).stdout.splitlines()

    def test_normal_session_loads_locked_adapter(self) -> None:
        output = self.run_wrapper("prompt")

        self.assertEqual("--extension", output[0])
        self.assertIn("pi-mcp-adapter/index.ts", output[1])
        self.assertEqual("--skill", output[2])
        self.assertIn("pi-mcp-adapter/skills", output[3])
        self.assertEqual(["prompt", "JJ_AGENT=pi"], output[4:])

    def test_one_shot_commands_remain_first_argument(self) -> None:
        for command in ("auth", "config", "install", "list", "remove", "uninstall", "update"):
            with self.subTest(command=command):
                self.assertEqual([command, "JJ_AGENT=pi"], self.run_wrapper(command))


if __name__ == "__main__":
    unittest.main()
