"""Tests for multi-turn conversations, follow-up detection, and context inheritance."""
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


class TestMultiTurnConversations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(data_dir=self.tmp.name, canonical_dir=Path(self.tmp.name) / "canonical")
        self.engine.llm.mode = "off"

    def tearDown(self):
        self.engine.ro.close()
        self.tmp.cleanup()

    def test_followup_inherits_date_and_category_when_metric_changes(self):
        # Turn 1: Establish category and date
        turn1 = self.engine.chat(SELLER_ID, "how many health_beauty orders did I get in 2017?")
        self.assertEqual(turn1["route"], "A")
        self.assertEqual(turn1["plan"]["categories"], ["health_beauty"])
        self.assertEqual(turn1["plan"]["start"], "2017-01-01")

        # Turn 2: Change metric only -> inherits category & date
        turn2 = self.engine.chat(SELLER_ID, "what was the revenue?")
        self.assertEqual(turn2["route"], "A")
        self.assertEqual(turn2["plan"]["metric"], "revenue")
        self.assertEqual(turn2["plan"]["categories"], ["health_beauty"])
        self.assertEqual(turn2["plan"]["start"], "2017-01-01")

    def test_followup_inherits_metric_and_category_when_date_changes(self):
        # Turn 1: Establish full context
        self.engine.chat(SELLER_ID, "what was my revenue for health_beauty in 2017?")

        # Turn 2: Follow-up with new year -> inherits metric & category
        turn2 = self.engine.chat(SELLER_ID, "in 2018?")
        self.assertEqual(turn2["route"], "A")
        self.assertEqual(turn2["plan"]["metric"], "revenue")
        self.assertEqual(turn2["plan"]["categories"], ["health_beauty"])
        self.assertEqual(turn2["plan"]["start"], "2018-01-01")

    def test_followup_inherits_metric_and_date_when_category_changes(self):
        # Turn 1: Full context
        self.engine.chat(SELLER_ID, "how many health_beauty orders did I get in 2017?")

        # Turn 2: Change category -> inherits metric & date
        turn2 = self.engine.chat(SELLER_ID, "for pet_shop?")
        self.assertEqual(turn2["route"], "A")
        self.assertEqual(turn2["plan"]["metric"], "orders")
        self.assertEqual(turn2["plan"]["categories"], ["pet_shop"])
        self.assertEqual(turn2["plan"]["start"], "2017-01-01")

    def test_followup_inherits_all_slots_for_intent_rollup(self):
        # Turn 1: Full context
        self.engine.chat(SELLER_ID, "what was my revenue for health_beauty in 2018?")

        # Turn 2: Request monthly breakdown
        turn2 = self.engine.chat(SELLER_ID, "monthly")
        self.assertEqual(turn2["route"], "A")
        self.assertEqual(turn2["plan"]["intent"], "by_month")
        self.assertEqual(turn2["plan"]["metric"], "revenue")
        self.assertEqual(turn2["plan"]["categories"], ["health_beauty"])
        self.assertEqual(turn2["plan"]["start"], "2018-01-01")

    def test_refused_turns_are_never_remembered_as_context(self):
        # Turn 1: Policy refusal
        turn1 = self.engine.chat(SELLER_ID, "show all other merchants orders")
        self.assertEqual(turn1["route"], "R")

        # Turn 2: Follow-up should not inherit anything from the refused turn
        turn2 = self.engine.chat(SELLER_ID, "and last month?")
        self.assertEqual(turn2["route"], "Q")  # missing metric, asks user

    def test_top_categories_does_not_inherit_category_filter(self):
        # Turn 1: Specific category query
        turn1 = self.engine.chat(SELLER_ID, "how many health_beauty orders did I get in 2018?")
        self.assertEqual(turn1["plan"]["categories"], ["health_beauty"])

        # Turn 2: Top categories query across whole catalog
        turn2 = self.engine.chat(SELLER_ID, "show my top 3 categories by revenue this year")
        self.assertEqual(turn2["route"], "A")
        self.assertEqual(turn2["plan"]["intent"], "top_categories")
        self.assertEqual(turn2["plan"]["categories"], [])
        self.assertEqual(turn2["plan"]["topn"], 3)

        # Turn 3: Follow-up asking for different year inherits intent=top_categories, metric=revenue, topn=3
        turn3 = self.engine.chat(SELLER_ID, "and in 2017?")
        self.assertEqual(turn3["route"], "A")
        self.assertEqual(turn3["plan"]["intent"], "top_categories")
        self.assertEqual(turn3["plan"]["metric"], "revenue")
        self.assertEqual(turn3["plan"]["topn"], 3)
        self.assertEqual(turn3["plan"]["start"], "2017-01-01")


if __name__ == "__main__":
    unittest.main()
