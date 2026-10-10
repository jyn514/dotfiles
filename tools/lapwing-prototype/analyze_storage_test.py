#!/usr/bin/env python3

import json
import random
import tempfile
import unittest
from pathlib import Path

import analyze_storage


class StorageAnalysisTest(unittest.TestCase):
    def test_load_words_keeps_unique_plain_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dictionary.json"
            path.write_text(json.dumps({
                "A": "Alpha",
                "B": "alpha",
                "C": "two words",
                "D": "{command}",
                "E": "beta",
            }))
            self.assertEqual(analyze_storage.load_words(path), ["alpha", "beta"])

    def test_generated_front_coding_roundtrips_with_independent_decoder(self) -> None:
        # Decode the byte format directly; never call the encoder's prefix/varint helpers.
        def decode(data, count, block):
            cursor = 0
            words = []

            def integer():
                nonlocal cursor
                value = shift = 0
                while True:
                    byte = data[cursor]
                    cursor += 1
                    value |= (byte & 127) << shift
                    if byte < 128:
                        return value
                    shift += 7
                    self.assertLessEqual(shift, 28)

            for index in range(count):
                prefix = 0 if index % block == 0 else integer()
                length = integer()
                if length >= 128:
                    seen.add("multibyte-suffix-length")
                suffix = data[cursor:cursor + length].decode("ascii")
                self.assertEqual(length, len(suffix))
                cursor += length
                previous = words[-1] if words else ""
                self.assertLessEqual(prefix, len(previous))
                words.append(previous[:prefix] + suffix)
            self.assertEqual(cursor, len(data))
            return words

        seed = 982173
        rng = random.Random(seed)
        cases = [[], [""], ["", "a", ""], ["a"], ["a", "a"], ["a", "ab", "abc"],
                 ["a" * 127, "a" * 128, "a" * 129 + "b"], ["z", "a"]]
        cases += [["".join(rng.choices("abcxyz", k=rng.randrange(1, 180)))
                   for _ in range(rng.randrange(2, 25))] for _ in range(60)]
        seen = set()
        for case, words in enumerate(cases):
            for block in (1, 2, 4, 8, 32):
                with self.subTest(seed=seed, case=case, words=words, block=block):
                    encoded = analyze_storage.front_code(iter(words), block)
                    self.assertEqual(words, decode(encoded, len(words), block))
                    if not words:
                        seen.add("empty")
                    if len(words) == 1:
                        seen.add("singleton")
                    if len(set(words)) < len(words):
                        seen.add("duplicates")
                    if "" in words:
                        seen.add("empty-word")
                    if any(a.startswith(b) or b.startswith(a)
                           for a, b in zip(words, words[1:])):
                        seen.add("shared-prefix")
                    if any(len(a) >= 128 and len(b) >= 128 and a[:128] == b[:128]
                           for a, b in zip(words, words[1:])):
                        seen.add("long-shared-prefix")
                    if words != sorted(words):
                        seen.add("unsorted")
                    if len(words) > block:
                        seen.add("restart")
                    if block == 1:
                        seen.add("all-restarts")
        self.assertEqual(seen, {"empty", "singleton", "duplicates", "long-shared-prefix", "multibyte-suffix-length", "empty-word",
                                "shared-prefix", "unsorted", "restart", "all-restarts"})

    def test_trie_shares_prefixes(self) -> None:
        nodes, edges, size = analyze_storage.estimate_trie(["car", "cart"])
        self.assertEqual((nodes, edges), (5, 4))
        self.assertGreater(size, 0)


if __name__ == "__main__":
    unittest.main()
