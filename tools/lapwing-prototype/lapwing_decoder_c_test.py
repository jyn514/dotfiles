#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path

import generate_c_rules

ROOT = Path(__file__).parent


class LapwingDecoderCTest(unittest.TestCase):
    def test_generated_rules_are_current(self) -> None:
        self.assertEqual(
            (ROOT / "lapwing_rules.generated.h").read_text(),
            generate_c_rules.generate(),
        )

    def test_c_decoder_recovers_representative_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "lapwing_decoder_test"
            subprocess.run(
                [
                    "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    "-O2", "-DLW_MAX_CANDIDATES=128",
                    str(ROOT / "lapwing_decoder.c"),
                    str(ROOT / "lapwing_decoder_test.c"),
                    "-o", str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
