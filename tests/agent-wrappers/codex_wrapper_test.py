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
            rules_directory = codex_home / "rules"
            rules_directory.mkdir()
            legacy_source = root / "tracked-codex.rules"
            legacy_source.write_text("legacy rules\n")
            os.link(legacy_source, rules_directory / "default.rules")
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
            rules = codex_home / "rules/default.rules"
            rendered_rules = rules.read_text()
            rules_mode = rules.stat().st_mode & 0o777
            legacy_rules = legacy_source.read_text()
            replaced_legacy_link = not os.path.samefile(legacy_source, rules)

        self.assertEqual(["--profile", "dotfiles", "-c"], output[:3])
        key, encoded = output[3].split("=", 1)
        self.assertEqual("developer_instructions", key)
        self.assertEqual("first instructions\n\nsecond instructions\n", json.loads(encoded))
        self.assertEqual("prompt", output[4])
        self.assertIn(str(ROOT / "libexec/agent-wrappers"), output[5])
        self.assertIn('deny(["sed"]', rendered_rules)
        self.assertIn('allow(["jj", ["status", "diff"', rendered_rules)
        self.assertEqual(0o600, rules_mode)
        self.assertEqual("legacy rules\n", legacy_rules)
        self.assertTrue(replaced_legacy_link)

    def test_failed_generation_preserves_rules_and_does_not_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            marker = root / "codex-ran"
            codex = fake_bin / "codex"
            codex.write_text(f"#!/bin/sh\ntouch {marker}\n")
            codex.chmod(0o755)
            bb = fake_bin / "bb"
            bb.write_text("#!/bin/sh\nprintf partial\nexit 7\n")
            bb.chmod(0o755)
            codex_home = root / ".codex"
            rules_directory = codex_home / "rules"
            rules_directory.mkdir(parents=True)
            published = rules_directory / "default.rules"
            published.write_text("previous rules\n")
            environment = os.environ | {
                "HOME": str(root),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            environment.pop("CODEX_HOME", None)

            result = subprocess.run(
                [str(WRAPPER)],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("cannot generate rules", result.stderr)
            self.assertEqual("previous rules\n", published.read_text())
            self.assertFalse(marker.exists())
            self.assertEqual([published], list(rules_directory.iterdir()))

    def test_sandbox_skips_permission_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            codex.chmod(0o755)
            codex_home = root / ".codex"
            codex_home.mkdir()
            manifest = codex_home / "developer-instructions.md"
            manifest.write_text("", encoding="utf-8")
            environment = os.environ | {
                "DOTFILES_SANDBOX": "1",
                "HOME": str(root),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            environment.pop("CODEX_HOME", None)

            result = subprocess.run(
                [str(WRAPPER), "prompt"],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("prompt", result.stdout.splitlines())
            self.assertFalse((codex_home / "rules").exists())


if __name__ == "__main__":
    unittest.main()
