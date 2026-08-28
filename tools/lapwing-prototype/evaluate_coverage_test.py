#!/usr/bin/env python3

import unittest

import evaluate_coverage


class EvaluateCoverageTest(unittest.TestCase):
    def test_tokenize_normalizes_words_and_preserves_internal_apostrophes(self) -> None:
        self.assertEqual(
            evaluate_coverage.tokenize("Cats, DON’T stop—re-enter 42."),
            ["cats", "don't", "stop", "re-enter"],
        )

    def test_frequency_report_uses_requested_frozen_cutoff(self) -> None:
        report = evaluate_coverage.frequency_report(
            [("common", 6.0), ("rare", 5.0)], {"common"}, 2
        )
        self.assertEqual(report["word_types"], 2)
        self.assertEqual(report["conventional_word_types"], 1)
        self.assertAlmostEqual(report["conventional_frequency_coverage"], 1 / 1.1)

    def test_missing_report_separates_source_and_rule_gaps(self) -> None:
        report = evaluate_coverage.missing_word_report(
            ["known", "tail", "missing", "absent", "absent"],
            {"known"}, ["known", "missing", "tail"], 2, {"known", "tail"},
        )
        self.assertEqual(
            report["categories"],
            {
                "below_selection_cutoff": {"tokens": 1, "word_types": 1},
                "absent_from_lapwing_stack": {"tokens": 1, "word_types": 1},
                "absent_from_frequency_source": {"tokens": 2, "word_types": 1},
            },
        )
        self.assertEqual(report["top_words"][0], {"word": "absent", "tokens": 2})

    def test_corpus_report_counts_tokens_not_only_types(self) -> None:
        report = evaluate_coverage.corpus_report(
            ["common", "common", "missing"], {"common"}
        )
        self.assertEqual(report["tokens"], 3)
        self.assertEqual(report["unique_word_types"], 2)
        self.assertEqual(report["conventional_tokens"], 2)
        self.assertAlmostEqual(report["conventional_token_coverage"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
