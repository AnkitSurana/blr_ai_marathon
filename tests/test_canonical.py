"""Tests verifying that editing canonical JSON files extends the pipeline without code changes."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["GUARDRAIL_LLM"] = "off"

from app.engine import DEMO_SELLERS, Engine

SELLER_ID = DEMO_SELLERS[0]


class TestCanonicalCustomizations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.canon_dir = Path(self.tmp.name) / "canonical"
        self.canon_dir.mkdir()
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _create_engine(self):
        return Engine(
            data_dir=str(self.data_dir),
            db_path=str(ROOT / "data" / "olist_seller.sqlite"),
            canonical_dir=str(self.canon_dir)
        )

    def test_vocabulary_alias_extension(self):
        """Adding an alias to vocabulary.json resolves queries to Route A."""
        (self.canon_dir / "vocabulary.json").write_text(json.dumps({
            "health_beauty": ["organic lotions"]
        }))
        engine = self._create_engine()
        response = engine.chat(SELLER_ID, "how many organic lotions orders in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["outcome"], "answered")
        self.assertEqual(response["plan"]["categories"], ["health_beauty"])

    def test_category_group_bundle_extension(self):
        """Adding a group term to groups.json expands to multiple categories."""
        (self.canon_dir / "groups.json").write_text(json.dumps({
            "beauty products": ["health_beauty", "perfumery"]
        }))
        engine = self._create_engine()
        response = engine.chat(SELLER_ID, "how many beauty products orders in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertIn("health_beauty", response["plan"]["categories"])
        self.assertIn("perfumery", response["plan"]["categories"])

    def test_calendar_promotional_window_extension(self):
        """Adding a date window to calendar.json makes promotional windows deterministic."""
        (self.canon_dir / "calendar.json").write_text(json.dumps({
            "summer sale": "06-15..06-30"
        }))
        engine = self._create_engine()
        response = engine.chat(SELLER_ID, "what was my revenue during summer sale 2018?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["plan"]["start"], "2018-06-15")
        self.assertEqual(response["plan"]["end"], "2018-06-30")

    def test_amounts_filter_extension(self):
        """Adding an amount filter to amounts.json appends a predicate to the SQL plan."""
        (self.canon_dir / "amounts.json").write_text(json.dumps({
            "high value items": {"column": "price", "op": ">=", "value": 300}
        }))
        engine = self._create_engine()
        response = engine.chat(SELLER_ID, "how many high value items did I sell in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["plan"]["amount"]["column"], "price")
        self.assertEqual(response["plan"]["amount"]["op"], ">=")
        self.assertEqual(response["plan"]["amount"]["value"], 300)

    def test_unsupported_scope_keyword_extension(self):
        """Adding custom refusal keywords to unsupported.json stops execution cleanly."""
        (self.canon_dir / "unsupported.json").write_text(json.dumps({
            "scope_words": ["inventory"]
        }))
        engine = self._create_engine()
        response = engine.chat(SELLER_ID, "show me inventory numbers for 2018")
        self.assertEqual(response["route"], "C")
        self.assertEqual(response["tokens"]["calls"], 0)


if __name__ == "__main__":
    unittest.main()
