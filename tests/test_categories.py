"""Tests for category matching, BM25 semantic scoring, and stemmer invariance."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import Engine
from app.matcher import clean_tokens, compare, is_one_edit_distance, score_all, stem


class TestCategoryMatchingAndStemmer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine()

    def test_stemmer_preserves_invariant_s_words(self):
        """Invariant nouns ending in 's' should never be corrupted."""
        invariants = ["lens", "bus", "gas", "status", "focus", "fitness", "business", "compass"]
        for word in invariants:
            self.assertEqual(stem(word), word, f"Stemmer corrupted invariant word '{word}'")

    def test_stemmer_normalizes_plurals(self):
        """Standard plural suffixes should stem cleanly."""
        self.assertEqual(stem("categories"), "category")
        self.assertEqual(stem("dresses"), "dress")
        self.assertEqual(stem("glasses"), "glass")
        self.assertEqual(stem("orders"), "order")

    def test_one_edit_distance(self):
        """Typo detection for 1-edit distance."""
        self.assertTrue(is_one_edit_distance("beauty", "beuty"))
        self.assertTrue(is_one_edit_distance("health", "helth"))
        self.assertFalse(is_one_edit_distance("beauty", "beauties"))

    def test_bm25_semantic_matching_on_canonical_categories(self):
        """Verify semantic category matching across various dataset categories."""
        test_cases = [
            ("earphones", "audio"),
            ("novels", "books_general_interest"),
            ("hvac", "air_conditioning"),
            ("laptops", "computers"),
            ("sofas", "furniture_living_room"),
            ("activewear", "fashion_sport"),
            ("smartphones", "telephony"),
            ("skincare", "health_beauty"),
            ("dumbbells", "sports_leisure"),
            ("action figures", "toys"),
            ("bedsheets", "bed_bath_table"),
            ("drills", "construction_tools_construction"),
            ("perfumes", "perfumery")
        ]
        for natural_phrase, expected_category in test_cases:
            tokens = clean_tokens(natural_phrase)
            ranked = score_all(tokens, self.engine.vocab)
            best_cat, score, via, cov = ranked[0]
            self.assertEqual(
                best_cat, expected_category,
                f"Phrase '{natural_phrase}' expected '{expected_category}' but matched '{best_cat}' (via '{via}')"
            )
            self.assertGreaterEqual(score, 0.60, f"Score for '{natural_phrase}' too low: {score}")


if __name__ == "__main__":
    unittest.main()
