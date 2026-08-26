#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import common_text_budget


class CommonTextBudgetTest(unittest.TestCase):
    def test_load_frequencies_filters_non_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frequencies.tsv"
            path.write_text("the\t7.7\n123\t6.0\ncan't\t5.9\n")
            self.assertEqual(
                common_text_budget.load_frequencies(path, 10),
                [("the", 7.7), ("can't", 5.9)],
            )

    def test_exception_storage_includes_records_and_output_words(self) -> None:
        self.assertEqual(common_text_budget.exception_storage_size(["python"]), 15)

    def test_exception_output_front_codes_lexical_neighbors(self) -> None:
        separate = (
            common_text_budget.exception_storage_size(["testing"])
            + common_text_budget.exception_storage_size(["tester"])
        )
        together = common_text_budget.exception_storage_size(["testing", "tester"])
        self.assertLess(together, separate)


if __name__ == "__main__":
    unittest.main()
