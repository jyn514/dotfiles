#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path

import generate_model

ROOT = Path(__file__).parent


class GenerateModelTest(unittest.TestCase):
    def test_model_is_deterministic_and_within_requested_shape(self) -> None:
        vocabulary = ["cat", "python", "people", "preview"]
        exceptions = [generate_model.ExceptionEntry("P", "people")]
        first = generate_model.pack_model(vocabulary, exceptions)
        second = generate_model.pack_model(vocabulary, exceptions)
        self.assertEqual(first, second)
        self.assertEqual(first[:4], generate_model.MAGIC)
        self.assertEqual(first[4], generate_model.VERSION)

    def test_c_model_lookup_and_rule_fallback(self) -> None:
        vocabulary = ["cat", "python", "people", "preview"]
        exceptions = [generate_model.ExceptionEntry("P", "people")]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model = directory / "model.bin"
            model.write_bytes(generate_model.pack_model(vocabulary, exceptions))
            executable = directory / "lapwing_model_test"
            subprocess.run(
                [
                    "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    "-O2", "-DLW_MAX_CANDIDATES=128",
                    str(ROOT / "lapwing_decoder.c"),
                    str(ROOT / "lapwing_model.c"),
                    str(ROOT / "lapwing_model_test.c"),
                    "-o", str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable), str(model)], check=True)

    def test_rejects_one_exception_outline_with_multiple_outputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "multiple outputs"):
            generate_model.pack_model(
                ["cat", "kat"],
                [
                    generate_model.ExceptionEntry("KAT", "cat"),
                    generate_model.ExceptionEntry("KAT", "kat"),
                ],
            )

    def test_rejects_exception_hash_collisions(self) -> None:
        original = generate_model.hash32
        try:
            generate_model.hash32 = lambda data, seed=2166136261: 7
            with self.assertRaisesRegex(ValueError, "hash collision"):
                generate_model.pack_model(
                    ["cat", "dog"],
                    [
                        generate_model.ExceptionEntry("KAT", "cat"),
                        generate_model.ExceptionEntry("TKOG", "dog"),
                    ],
                )
        finally:
            generate_model.hash32 = original


if __name__ == "__main__":
    unittest.main()
