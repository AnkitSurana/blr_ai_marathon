"""Tests for single-turn query execution, intent routing, and SQL templates."""
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


class TestSingleTurnQueries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(data_dir=self.tmp.name, canonical_dir=Path(self.tmp.name) / "canonical")
        self.engine.llm.mode = "off"

    def tearDown(self):
        self.engine.ro.close()
        self.tmp.cleanup()

    def test_orders_metric_query(self):
        """Query for order count in a specific category and year."""
        response = self.engine.chat(SELLER_ID, "how many health_beauty orders did I get in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["outcome"], "answered")
        self.assertEqual(response["tokens"]["calls"], 0)
        self.assertEqual(response["plan"]["metric"], "orders")
        self.assertEqual(response["plan"]["categories"], ["health_beauty"])
        self.assertEqual(response["plan"]["start"], "2017-01-01")
        self.assertEqual(response["plan"]["end"], "2017-12-31")

    def test_revenue_metric_query(self):
        """Query for revenue earned in a category."""
        response = self.engine.chat(SELLER_ID, "what was my revenue from health_beauty in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["outcome"], "answered")
        self.assertEqual(response["plan"]["metric"], "revenue")

    def test_items_sold_metric_query(self):
        """Query for unit items sold."""
        response = self.engine.chat(SELLER_ID, "how many units of health_beauty did I sell in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["outcome"], "answered")
        self.assertEqual(response["plan"]["metric"], "items")

    def test_top_categories_ranking_intent(self):
        """Query for top categories ranking."""
        response = self.engine.chat(SELLER_ID, "what were my top 5 categories by revenue in 2017?")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["plan"]["intent"], "top_categories")
        self.assertEqual(response["plan"]["topn"], 5)

    def test_monthly_rollup_intent(self):
        """Query for month-by-month breakdown."""
        response = self.engine.chat(SELLER_ID, "show me monthly revenue for health_beauty in 2017")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["plan"]["intent"], "by_month")

    def test_list_records_intent(self):
        """Query to list individual order records."""
        response = self.engine.chat(SELLER_ID, "list my orders for health_beauty in 2017")
        self.assertEqual(response["route"], "A")
        self.assertEqual(response["plan"]["intent"], "list_records")

    def test_clarify_when_metric_is_missing(self):
        """Query with no metric asks the user for clarification (Route Q)."""
        response = self.engine.chat(SELLER_ID, "how did health_beauty do in 2017?")
        self.assertEqual(response["route"], "Q")
        self.assertEqual(response["outcome"], "clarify")
        self.assertIn("What would you like me to measure", response["reply"])


if __name__ == "__main__":
    unittest.main()
