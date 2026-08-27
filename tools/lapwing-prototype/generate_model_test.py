#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path

import generate_model

ROOT = Path(__file__).parent


class GenerateModelTest(unittest.TestCase):
    def test_productive_outlines_include_inflections_possessives_and_fragments(self) -> None:
        outlines = {
            "day": ["TKAEU"],
            "world": ["WORLD"],
            "success": ["SUK/SES"],
        }
        generate_model.add_productive_outlines(
            outlines,
            ["days", "world's", "anti", "non", "im", "usa", "sydney",
             "successful", "successfully"],
        )
        self.assertIn("TKAEU/-Z", outlines["days"])
        self.assertIn("WORLD/AES", outlines["world's"])
        self.assertEqual(outlines["anti"], ["APB/TEU"])
        self.assertEqual(outlines["non"], ["TPHOPB"])
        self.assertEqual(outlines["im"], ["EUPL"])
        self.assertEqual(outlines["usa"], ["U*/S*/A*"])
        self.assertEqual(outlines["sydney"], ["S*/KWH*/TK*/TPH*/E*/KWH*"])
        self.assertIn("SUK/SES/-FL", outlines["successful"])
        self.assertIn("SUK/SES/-FL/HREU", outlines["successfully"])

    def test_model_is_deterministic_and_within_requested_shape(self) -> None:
        vocabulary = ["cat", "python", "people", "preview"]
        exceptions = [generate_model.ExceptionEntry("P", "people")]
        first = generate_model.pack_model(vocabulary, exceptions)
        second = generate_model.pack_model(vocabulary, exceptions)
        self.assertEqual(first, second)
        self.assertEqual(first[:4], generate_model.MAGIC)
        self.assertEqual(first[4], generate_model.VERSION)

    def test_fast_exception_sizing_matches_serialization(self) -> None:
        vocabulary = ["cat", "python", "people", "preview"]
        exceptions = [
            generate_model.ExceptionEntry("P", "people"),
            generate_model.ExceptionEntry("PRAOE/SRAOU", "preview"),
        ]
        dawg = generate_model.build_dawg(vocabulary)
        model = generate_model.pack_model(vocabulary, exceptions, dawg)
        self.assertEqual(
            len(model) - generate_model.HEADER.size - len(dawg[0]),
            generate_model.exception_storage_size(exceptions),
        )

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

    def test_exception_local_search_replaces_lower_weight_word(self) -> None:
        low = generate_model.ExceptionEntry("HROE", "low")
        high = generate_model.ExceptionEntry("TOP", "top")
        budget = generate_model.exception_storage_size([low])
        improved = generate_model.improve_exception_selection(
            [low], [low, high], {"low": 1.0, "top": 2.0}, 0, budget
        )
        self.assertEqual(improved, [high])

    def test_model_selection_builds_vocabulary_graph_once(self) -> None:
        dictionary = {"KAT": "cat", "TKOG": "dog"}
        frequencies = [("cat", 7.0), ("dog", 6.0)]
        original = generate_model.build_dawg
        calls = 0

        def counted(words):
            nonlocal calls
            calls += 1
            return original(words)

        try:
            generate_model.build_dawg = counted
            generate_model.choose_model(dictionary, frequencies, 2, 24, 4096)
        finally:
            generate_model.build_dawg = original
        self.assertEqual(calls, 1)

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
