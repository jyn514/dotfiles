#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIFF_CHECK = ROOT / "lib" / "agent-wrappers" / "diff-check"


class DiffCheckTest(unittest.TestCase):
    def run_diff_check(self, diff: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            jj = bin_dir / "jj"
            jj.write_text("#!/bin/sh\nprintf '%s' \"$JJ_DIFF\"\n")
            jj.chmod(0o755)
            env = os.environ | {
                "JJ_DIFF": diff,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            }
            return subprocess.run(
                [DIFF_CHECK],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_allows_blank_context_line_in_patch_file(self) -> None:
        result = self.run_diff_check(
            "diff --git a/change.patch b/change.patch\n"
            "--- a/change.patch\n"
            "+++ b/change.patch\n"
            "@@ -0,0 +1,2 @@\n"
            "+ context\n"
            "+ \n"
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_allows_blank_context_line_in_diff_file(self) -> None:
        result = self.run_diff_check(
            "diff --git a/change.diff b/change.diff\n"
            "--- a/change.diff\n"
            "+++ b/change.diff\n"
            "@@ -0,0 +1 @@\n"
            "+ \n"
        )

        self.assertEqual(result.returncode, 0)

    def test_rejects_blank_whitespace_line_in_other_file(self) -> None:
        result = self.run_diff_check(
            "diff --git a/code.txt b/code.txt\n"
            "--- a/code.txt\n"
            "+++ b/code.txt\n"
            "@@ -0,0 +1 @@\n"
            "+ \n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "+ \n")

    def test_rejects_other_trailing_whitespace_in_patch_file(self) -> None:
        result = self.run_diff_check(
            "diff --git a/change.patch b/change.patch\n"
            "--- a/change.patch\n"
            "+++ b/change.patch\n"
            "@@ -0,0 +1 @@\n"
            "++added \n"
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "++added \n")


if __name__ == "__main__":
    unittest.main()
