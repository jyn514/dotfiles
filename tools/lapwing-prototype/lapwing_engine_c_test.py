#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path

import generate_model

ROOT = Path(__file__).parent


class LapwingEngineCTest(unittest.TestCase):
    def test_delayed_multistroke_translation_punctuation_and_undo(self) -> None:
        vocabulary = ["cat", "python"]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model = directory / "model.bin"
            model.write_bytes(generate_model.pack_model(vocabulary, []))
            executable = directory / "lapwing_engine_test"
            subprocess.run(
                [
                    "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
                    "-DLW_MAX_CANDIDATES=128",
                    str(ROOT / "lapwing_decoder.c"), str(ROOT / "lapwing_model.c"),
                    str(ROOT / "lapwing_engine.c"), str(ROOT / "lapwing_engine_test.c"),
                    "-o", str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable), str(model)], check=True)


if __name__ == "__main__":
    unittest.main()
