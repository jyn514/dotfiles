#!/usr/bin/env python3

import unittest

import learn_chunks


class ChunkLearningTest(unittest.TestCase):
    def test_balanced_parts_preserves_word(self) -> None:
        parts = learn_chunks.balanced_parts("python", 2)
        self.assertEqual("".join(parts), "python")
        self.assertTrue(all(parts))

    def test_candidates_recompose_chunks_and_filter_vocabulary(self) -> None:
        model = {
            "PAOEU": {"py": 3, "pi": 1},
            "THON": {"thon": 3},
        }
        result = learn_chunks.candidates(
            ("PAOEU", "THON"), model, {"python"}, k=5, per_stroke=4, beam=100
        )
        self.assertEqual(result, ["python"])

    def test_learning_records_each_stroke(self) -> None:
        model, usable = learn_chunks.learn(
            [(("PAOEU", "THON"), "python")], iterations=2, alpha=0.1
        )
        self.assertEqual(usable, 1)
        self.assertEqual(set(model), {"PAOEU", "THON"})

    def test_unknown_stroke_has_no_candidate(self) -> None:
        self.assertEqual(
            learn_chunks.candidates(("?",), {}, {"word"}, 5, 4, 100), []
        )


if __name__ == "__main__":
    unittest.main()
