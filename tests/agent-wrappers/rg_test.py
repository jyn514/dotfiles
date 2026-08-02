#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "libexec" / "agent-wrappers" / "rg"


class RgWrapperTest(unittest.TestCase):
    def run_wrapper(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            real_rg = temp_dir / "rg"
            real_rg.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            real_rg.chmod(0o755)
            return subprocess.run(
                [WRAPPER, *arguments],
                env=os.environ
                | {
                    "PATH": os.pathsep.join(
                        (str(WRAPPER.parent), str(temp_dir), os.environ["PATH"])
                    ),
                    "RIPGREP_CONFIG_PATH": str(temp_dir / "hostile-config"),
                },
                text=True,
                capture_output=True,
                check=False,
            )

    def test_forwards_search_with_configuration_disabled(self) -> None:
        result = self.run_wrapper("needle", "haystack")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["--no-config", "needle", "haystack"])

    def test_rejects_pre_with_separate_command(self) -> None:
        result = self.run_wrapper("--pre", "sh -c evil", "needle")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "rg wrapper: --pre is not permitted\n")

    def test_rejects_pre_with_equals_command(self) -> None:
        result = self.run_wrapper("--pre=sh -c evil", "needle")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_rejects_pre_glob_in_both_forms(self) -> None:
        for arguments in (("--pre-glob", "*.pdf"), ("--pre-glob=*.pdf",)):
            with self.subTest(arguments=arguments):
                result = self.run_wrapper(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_rejects_hostname_bin_in_both_forms(self) -> None:
        for arguments in (
            ("--hostname-bin", "evil"),
            ("--hostname-bin=evil",),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_wrapper(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr,
                    "rg wrapper: --hostname-bin is not permitted\n",
                )


if __name__ == "__main__":
    unittest.main()
