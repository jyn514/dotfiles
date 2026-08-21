#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "bin/codex"


class CodexWrapperTests(unittest.TestCase):
    def test_injects_shared_voice_as_developer_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nprintf "PATH=%s\\n" "$PATH"\n')
            codex.chmod(0o755)
            codex_home = root / ".codex"
            codex_home.mkdir()
            first = codex_home / "first.md"
            second = codex_home / "second file.md"
            first.write_text("first instructions\n", encoding="utf-8")
            second.write_text("second instructions", encoding="utf-8")
            manifest = codex_home / "developer-instructions.md"
            manifest.write_text("# Shared instruction files\n@first.md\n@second file.md\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["HOME"] = str(root)
            environment.pop("CODEX_HOME", None)
            environment.pop("CODEX_DEVELOPER_INSTRUCTIONS_FILE", None)
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

            output = subprocess.run(
                [str(WRAPPER), "prompt"],
                check=True,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.splitlines()

        self.assertEqual("-c", output[0])
        key, encoded = output[1].split("=", 1)
        self.assertEqual("developer_instructions", key)
        self.assertEqual("first instructions\n\nsecond instructions\n", json.loads(encoded))
        self.assertEqual("prompt", output[2])
        self.assertIn(str(ROOT / "libexec/agent-wrappers"), output[3])


if __name__ == "__main__":
    unittest.main()
