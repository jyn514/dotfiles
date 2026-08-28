#!/usr/bin/env python3

import hashlib
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
            "account": ["K-T"],
            "accountability": ["BAD"],
            "battle": ["PWAT/-L"],
            "field": ["TPAO*ELD"],
            "battlefield": ["OTHER"],
        }
        generate_model.add_productive_outlines(
            outlines,
            ["days", "world's", "anti", "non", "im", "mis",
             "successful", "successfully", "accountability", "battlefield"],
        )
        self.assertIn("TKAEU/-Z", outlines["days"])
        self.assertIn("WORLD/AES", outlines["world's"])
        self.assertIn("APB/TEU", outlines["anti"])
        self.assertIn("TPHOPB", outlines["non"])
        self.assertIn("EUPL", outlines["im"])
        self.assertIn("PHEUS", outlines["mis"])
        self.assertIn("SUK/SES/-FL", outlines["successful"])
        self.assertIn("SUK/SES/-FL/HREU", outlines["successfully"])
        self.assertIn("K-T/-BLT", outlines["accountability"])
        self.assertIn("PWAT/-L/TPAO*ELD", outlines["battlefield"])

    def test_productive_outlines_compose_multiple_hyphenated_components(self) -> None:
        outlines = {
            "if": ["EUF"],
            "none": ["TPHAUPB"],
            "match": ["PHAFP"],
        }
        generate_model.add_productive_outlines(outlines, ["if-none-match"])
        self.assertIn("EUF/TPHAUPB/PHAFP", outlines["if-none-match"])

    def test_regular_spelling_variants_reuse_source_outlines(self) -> None:
        outlines = {
            "honor": ["HO/TPHOR"],
            "recognize": ["REZ"],
            "center": ["SEPB/TER"],
            "traveled": ["TRAFLD"],
        }
        generate_model.add_productive_outlines(
            outlines, ["honour", "recognise", "centre", "travelled"]
        )
        self.assertIn("HO/TPHOR", outlines["honour"])
        self.assertIn("REZ", outlines["recognise"])
        self.assertIn("SEPB/TER", outlines["centre"])
        self.assertIn("TRAFLD", outlines["travelled"])

    def test_write_out_synthesis_uses_observed_non_fingerspelling_strokes(self) -> None:
        outlines = {
            "first chunk": ["PAOEU"],
            "second chunk": ["THOPB"],
        }
        generate_model.add_productive_outlines(outlines, ["python"])
        self.assertIn("PAOEU/THOPB", outlines["python"])

    def test_write_out_synthesis_does_not_relabel_fingerspelling(self) -> None:
        outlines = {
            "letter a": ["A*"],
            "letter b": ["PW*"],
        }
        generate_model.add_productive_outlines(outlines, ["abab"])
        self.assertNotIn("abab", outlines)

    def test_synthesized_roots_receive_productive_morphology(self) -> None:
        outlines = {
            "first chunk": ["PAOEU"],
            "second chunk": ["THOPB"],
        }
        generate_model.add_productive_outlines(outlines, ["python", "pythons"])
        self.assertIn("PAOEU/THOPB/-Z", outlines["pythons"])

    def test_model_is_deterministic_and_within_requested_shape(self) -> None:
        vocabulary = ["cat", "python", "people", "preview"]
        exceptions = [generate_model.ExceptionEntry("P", "people")]
        first = generate_model.pack_model(vocabulary, exceptions)
        second = generate_model.pack_model(vocabulary, exceptions)
        self.assertEqual(first, second)
        self.assertEqual(first[:4], generate_model.MAGIC)
        self.assertEqual(first[4], generate_model.VERSION)

    def test_word_delta_uses_nibbles_and_escapes_long_lengths(self) -> None:
        self.assertEqual(generate_model.encode_word_delta(14, 14), b"\xee")
        self.assertEqual(generate_model.encode_word_delta(15, 1), b"\xff\x0f\x01")
        self.assertEqual(generate_model.word_delta_size(15, 1), 3)

    def test_incremental_exception_sizing_matches_full_calculation(self) -> None:
        def word(number: int) -> str:
            letters = []
            for _ in range(4):
                number, remainder = divmod(number, 26)
                letters.append(chr(97 + remainder))
            return "w" + "".join(reversed(letters))

        for count in (0, 1, 31, 383, 384, 385, 767):
            words = [word(index * 2) for index in range(count)]
            entries = [generate_model.ExceptionEntry(f"O{index}", value)
                       for index, value in enumerate(words)]
            current_size = generate_model.exception_storage_size(entries)
            for insertion in (0, count // 2, count):
                candidate = word(insertion * 2 + 1)
                proposed = entries + [generate_model.ExceptionEntry("NEW", candidate)]
                self.assertEqual(
                    generate_model.exception_storage_size_after_insert(
                        words, current_size, candidate,
                    ),
                    generate_model.exception_storage_size(proposed),
                    (count, insertion),
                )
            for removal in {0, count // 2, count - 1} if count else ():
                reduced_size, reduced_words = (
                    generate_model.exception_storage_size_after_remove(
                        words, current_size, removal,
                    )
                )
                self.assertEqual(reduced_words, words[:removal] + words[removal + 1:])
                self.assertEqual(
                    reduced_size,
                    generate_model.exception_storage_size(
                        entries[:removal] + entries[removal + 1:]
                    ),
                    (count, removal),
                )

    def test_node_exception_sizing_matches_serialization(self) -> None:
        vocabulary = ["cat", "python", "people", "preview"]
        exceptions = [
            generate_model.ExceptionEntry("P", "people"),
            generate_model.ExceptionEntry("PRAOE/SRAOU", "preview"),
        ]
        dawg = generate_model.build_dawg(vocabulary)
        model = generate_model.pack_model(vocabulary, exceptions, dawg)
        self.assertEqual(
            len(model) - generate_model.HEADER.size - len(dawg[0]),
            generate_model.node_exception_storage_size(
                len(exceptions), dawg[2] + 1,
            ),
        )

    def test_node_exception_requires_primary_output(self) -> None:
        vocabulary = ["cat"]
        with self.assertRaisesRegex(ValueError, "not a primary trie word"):
            generate_model.pack_model(
                vocabulary, [generate_model.ExceptionEntry("TKOG", "dog")]
            )

    def test_c_model_lookup_and_rule_fallback(self) -> None:
        vocabulary = ["abcdefghijklmnopq", "abcdefghijklmnopqr", "called", "cat", "cat-fish", "celebration", "centre", "clean", "college", "doing", "don't", "flame", "honour", "john", "light", "love", "makes", "placed", "possess", "python", "people", "preview", "talk", "transmission", "travelled", "watch"]
        exceptions = [
            generate_model.ExceptionEntry("#SKWRO*PB", "john"),
            generate_model.ExceptionEntry("LONG1", "abcdefghijklmnopq"),
            generate_model.ExceptionEntry("LONG2", "abcdefghijklmnopqr"),
            generate_model.ExceptionEntry("P", "people"),
        ]
        for number in range(400):
            quotient, last = divmod(number, 26)
            first, middle = divmod(quotient, 26)
            word = "q" + chr(97 + first) + chr(97 + middle) + chr(97 + last)
            vocabulary.append(word)
            exceptions.append(generate_model.ExceptionEntry(f"DUMMY{number}", word))
        overflow_words = sorted({
            "z" + "".join(chr(97 + byte % 26) for byte in hashlib.sha256(
                str(number).encode()
            ).digest()[:7])
            for number in range(3000)
        })
        vocabulary.extend(overflow_words)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            model = directory / "model.bin"
            dawg = generate_model.build_dawg(vocabulary)
            old_packed_edge_bytes = (dawg[2] * 20 + 7) // 8
            self.assertLess(len(dawg[0]), old_packed_edge_bytes)
            labels, topology, terminals, checkpoints = generate_model.louds_sections(
                dawg[0], dawg[2],
            )
            self.assertTrue(labels and topology and terminals and checkpoints)
            cat_id = generate_model.primary_root_ids(vocabulary, dawg)["cat"]
            morphology = [generate_model.MorphologyGroup("", "s", (cat_id,))]
            model.write_bytes(generate_model.pack_model(
                vocabulary, exceptions, dawg, morphology,
            ))
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

    def test_grouped_morphology_is_exact_and_delta_coded(self) -> None:
        vocabulary = ["cat", "dog"]
        dawg = generate_model.build_dawg(vocabulary)
        ids = generate_model.primary_root_ids(vocabulary, dawg)
        group = generate_model.MorphologyGroup("", "s", tuple(sorted(ids.values())))
        encoded = generate_model.encode_morphology([group])
        self.assertLess(len(encoded), 2 * 5)  # cheaper than two exception records
        self.assertEqual(
            generate_model.pack_model(vocabulary, [], dawg, [group]),
            generate_model.pack_model(vocabulary, [], dawg, [group]),
        )

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

    def test_model_selection_reuses_outline_generation_results(self) -> None:
        original = generate_model.hand_rules.generate_outline
        calls: list[tuple[str, bool]] = []

        def counted(outline, beam, prefixes=None, prune_final=True):
            calls.append((outline, prune_final))
            if outline == "KATS":
                return [] if prune_final else ["cats"]
            return original(outline, beam, prefixes, prune_final)

        try:
            generate_model.hand_rules.generate_outline = counted
            generate_model.choose_model(
                {"KAT": "cat", "KATS": "cats"},
                [("cat", 7.0), ("cats", 6.0)],
                2, 24, 4096,
            )
        finally:
            generate_model.hand_rules.generate_outline = original
        self.assertEqual(calls.count(("KATS", False)), 1)

    def test_vocabulary_rebalance_replaces_outline_less_tail_token(self) -> None:
        vocabulary, _, report = generate_model.choose_model(
            {"KAT": "cat", "PWEURD": "bird"},
            [("cat", 7.0), ("xx", 6.0), ("bird", 5.0)],
            2, 24, 4096,
        )
        self.assertEqual(vocabulary, ["cat", "bird"])
        self.assertEqual(report["vocabulary_rebalance_removals"], 1)
        self.assertEqual(report["vocabulary_rebalance_additions"], 1)

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
