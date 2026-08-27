#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import merge_dictionaries


class MergeDictionariesTest(unittest.TestCase):
    def test_earlier_dictionary_has_lookup_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            high = root / "high.json"
            low = root / "low.json"
            high.write_text(json.dumps({"#SKWRO*PB": "John", "KAT": "kat"}))
            low.write_text(json.dumps({"KAT": "cat", "TKOG": "dog"}))
            self.assertEqual(
                merge_dictionaries.merge_dictionaries([high, low]),
                {"#SKWRO*PB": "John", "KAT": "kat", "TKOG": "dog"},
            )

    def test_rejects_non_string_dictionary_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"KAT": 3}))
            with self.assertRaisesRegex(ValueError, "string-to-string"):
                merge_dictionaries.merge_dictionaries([path])


if __name__ == "__main__":
    unittest.main()
