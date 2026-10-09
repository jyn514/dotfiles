#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "libexec" / "agent-wrappers" / "rg"


class RgWrapperTest(unittest.TestCase):
    def test_public_symlink_reaches_private_binary_with_config_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root / "opt" / "agent-tools" / "bin"
            public.mkdir(parents=True)
            public_rg = public / "rg"
            public_rg.symlink_to(WRAPPER)
            real_rg = root / "real-rg"
            real_rg.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            real_rg.chmod(0o755)

            result = subprocess.run(
                [public_rg, "needle", "haystack"],
                env=os.environ
                | {
                    "RG_REAL": str(real_rg),
                    "RIPGREP_CONFIG_PATH": str(root / "hostile-config"),
                },
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["--no-config", "needle", "haystack"], result.stdout.splitlines()
        )

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
                    "RG_REAL": str(real_rg),
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

    def test_forwards_protected_strings_as_pattern_values(self) -> None:
        for pattern in ("--pre", "--pre=evil", "--pre-glob", "--hostname-bin=evil"):
            for prefix in (("-e",), ("--regexp",), ("-ne",), ("--hidden", "-e")):
                arguments = (*prefix, pattern, "haystack")
                with self.subTest(arguments=arguments):
                    result = self.run_wrapper(*arguments)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout.splitlines(), ["--no-config", *arguments]
                    )

    def test_forwards_literal_paths_after_option_terminator(self) -> None:
        result = self.run_wrapper("-e", "needle", "--", "--pre", "--hostname-bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["--no-config", "-e", "needle", "--", "--pre", "--hostname-bin"],
        )

    def test_option_values_do_not_disguise_executable_options(self) -> None:
        for prefix in (
            ("--glob", "-e"), ("-g", "-e"), ("-ng", "-e"), ("-g-e",),
            ("--glob", "--"), ("--unknown", "-e"), ("-e", "--"),
        ):
            with self.subTest(prefix=prefix):
                result = self.run_wrapper(*prefix, "--pre", "evil", "needle")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_rejects_executable_options_after_literal_pattern(self) -> None:
        result = self.run_wrapper("-e", "--pre", "--hostname-bin", "evil")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "rg wrapper: --hostname-bin is not permitted\n")

    def test_literal_pattern_reaches_real_ripgrep(self) -> None:
        real_rg = os.environ.get("DOTFILES_TEST_RG_REAL") or shutil.which("rg")
        if real_rg is None:
            self.skipTest("ripgrep is not installed")
        result = subprocess.run(
            [WRAPPER, "--line-number", "--hidden", "-e", "--pre"],
            input="ordinary\n--pre\n",
            env=os.environ | {"RG_REAL": real_rg},
            text=True, capture_output=True, check=False, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "2:--pre\n")

    def test_pi_grep_argument_sequence_reaches_real_ripgrep(self) -> None:
        real_rg = os.environ.get("DOTFILES_TEST_RG_REAL") or shutil.which("rg")
        if real_rg is None:
            self.skipTest("ripgrep is not installed")
        result = subprocess.run(
            [
                WRAPPER, "--json", "--line-number", "--color=never",
                "--hidden", "--", "--pre",
            ],
            input="ordinary\n--pre\n",
            env=os.environ | {"RG_REAL": real_rg},
            text=True, capture_output=True, check=False, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        matches = [
            event["data"] for line in result.stdout.splitlines()
            if (event := json.loads(line))["type"] == "match"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["line_number"], 2)
        self.assertEqual(matches[0]["lines"]["text"], "--pre\n")

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
