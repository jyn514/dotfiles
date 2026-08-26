#!/usr/bin/env python3

import unittest

import hand_rules


class HandRulesTest(unittest.TestCase):
    def test_parse_stroke(self) -> None:
        self.assertEqual(hand_rules.parse_stroke("PAOEU"), ("P", "AOEU", "", False))
        self.assertEqual(hand_rules.parse_stroke("-PLT"), ("", "", "PLT", False))
        self.assertEqual(hand_rules.parse_stroke("PA*T"), ("P", "A", "T", True))

    def test_regular_single_stroke_words(self) -> None:
        vocabulary = {"cat", "motion", "hitch", "path"}
        self.assertEqual(hand_rules.decode_outline("KAT", vocabulary, 1000, 10)[0], "cat")
        self.assertIn("motion", hand_rules.decode_outline("PHOEGS", vocabulary, 1000, 10))
        self.assertIn("hitch", hand_rules.decode_outline("HEUFP", vocabulary, 1000, 10))
        self.assertIn("path", hand_rules.decode_outline("PA*T", vocabulary, 1000, 10))

    def test_syllables_and_affixes(self) -> None:
        vocabulary = {"python", "preview", "helpful", "treatment", "crazy"}
        cases = {
            "PAOEU/THOPB": "python",
            "PRAOE/SRAOU": "preview",
            "HEL/-P/-FL": "helpful",
            "TRAOET/-PLT": "treatment",
            "KRAEUZ/KWREU": "crazy",
        }
        for outline, expected in cases.items():
            with self.subTest(outline=outline):
                self.assertIn(expected, hand_rules.decode_outline(outline, vocabulary, 10000, 10))

    def test_silent_e_and_folded_morphology(self) -> None:
        vocabulary = {"snake", "zapping", "snakes"}
        self.assertIn("snake", hand_rules.decode_outline("STPHAEUBG", vocabulary, 10000, 10))
        self.assertIn("zapping", hand_rules.decode_outline("STKPWAPG", vocabulary, 10000, 10))
        self.assertIn("snakes", hand_rules.decode_outline("STPHAEUBGZ", vocabulary, 10000, 10))

    def test_productive_prefix_and_suffix_families(self) -> None:
        vocabulary = {"stabilized", "interstate", "microphone"}
        self.assertIn("stabilized", hand_rules.decode_outline("STAEU/PWEUL/KWRAOEUDZ", vocabulary, 10000, 10))
        self.assertIn("interstate", hand_rules.decode_outline("EURPBT/STAEUT", vocabulary, 10000, 10))
        self.assertIn("microphone", hand_rules.decode_outline("PHAOEURBG/TPO*EPB", vocabulary, 10000, 10))

    def test_rule_table_is_small(self) -> None:
        self.assertLess(hand_rules.packed_rule_size(), 4096)


if __name__ == "__main__":
    unittest.main()
