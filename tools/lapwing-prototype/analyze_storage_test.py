#!/usr/bin/env python3

import json
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

    def test_front_coding_round_trip_shape(self) -> None:
        words = ["alpha", "alpine", "beta"]
        encoded = analyze_storage.front_code(words, block_size=2)
        self.assertLess(len(encoded), len("\n".join(words)) + 3)

    def test_trie_shares_prefixes(self) -> None:
        nodes, edges, size = analyze_storage.estimate_trie(["car", "cart"])
        self.assertEqual((nodes, edges), (5, 4))
        self.assertGreater(size, 0)


if __name__ == "__main__":
    unittest.main()
