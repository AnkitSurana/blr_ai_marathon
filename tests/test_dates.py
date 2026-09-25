"""Tests for deterministic date parsing, ISO ranges, rolling periods, and business calendars."""
import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dates import parse_dates
from app.engine import TODAY


class TestDateParsing(unittest.TestCase):
    def parse(self, text: str):
        result = parse_dates(text, TODAY)
        return result.status, result.iso(), result.flags

    def test_explicit_calendar_year(self):
        status, (start, end), _ = self.parse("in 2017")
        self.assertEqual(status, "resolved")
        self.assertEqual((start, end), ("2017-01-01", "2017-12-31"))

    def test_relative_last_quarter(self):
        # Today is 2018-09-01 (Q3). Last quarter was Q2 2018 (Apr 1 - Jun 30).
        status, (start, end), _ = self.parse("last quarter")
        self.assertEqual(status, "resolved")
        self.assertEqual((start, end), ("2018-04-01", "2018-06-30"))

    def test_relative_last_month(self):
        # Today is 2018-09-01. Last month was August 2018 (Aug 1 - Aug 31).
        status, (start, end), _ = self.parse("last month")
        self.assertEqual(status, "resolved")
        self.assertEqual((start, end), ("2018-08-01", "2018-08-31"))

    def test_rolling_last_3_months(self):
        status, (start, end), _ = self.parse("in the last 3 months")
        self.assertEqual(status, "resolved")
        self.assertEqual((start, end), ("2018-06-01", "2018-08-31"))

    def test_quarter_phrasings_equivalence(self):
        expected_window = ("2017-07-01", "2017-09-30")
        phrasings = [
            "Q3 2017",
            "Q3'17",
            "third quarter of 2017",
            "2017 Q3",
            "quarter 3 of 2017",
            "between July and September 2017"
        ]
        for phrase in phrasings:
            status, iso_range, _ = self.parse(phrase)
            self.assertEqual(status, "resolved", f"Failed to parse '{phrase}'")
            self.assertEqual(iso_range, expected_window, f"Mismatch for '{phrase}'")

    def test_month_and_year_numeric(self):
        status, (start, end), _ = self.parse("in 03/2018")
        self.assertEqual(status, "resolved")
        self.assertEqual((start, end), ("2018-03-01", "2018-03-31"))


if __name__ == "__main__":
    unittest.main()
