#!/usr/bin/env python3

import unittest

import generate_wordfreq


class GenerateWordfreqTest(unittest.TestCase):
    def test_render_frequencies_preserves_order_and_scores(self) -> None:
        scores = {"the": 7.73, "to": 7.43}
        self.assertEqual(
            generate_wordfreq.render_frequencies(["the", "to"], scores.__getitem__),
            b"the\t7.73\nto\t7.43\n",
        )


if __name__ == "__main__":
    unittest.main()
