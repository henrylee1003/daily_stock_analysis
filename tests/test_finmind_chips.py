# -*- coding: utf-8 -*-
# Usage: python -m pytest tests/test_finmind_chips.py -q
# Description: Tests for FinMind chip parsing and compact-report flow selection
# Input: None (FinMind HTTP calls are mocked)
# Output: pytest results
# Dependencies: pytest
"""Tests for src.finmind_chips and the chip lines in src.compact_report."""

import unittest
from datetime import date
from unittest import mock

import src.compact_report as cr
import src.finmind_chips as fc


def _inst_rows(day="2026-11-17"):
    return [
        {"date": "2026-11-16", "name": "Foreign_Investor", "buy": 1, "sell": 999999},
        {"date": day, "name": "Foreign_Investor", "buy": 782755, "sell": 900552},
        {"date": day, "name": "Foreign_Dealer_Self", "buy": 2000, "sell": 0},
        {"date": day, "name": "Investment_Trust", "buy": 197235, "sell": 51715},
        {"date": day, "name": "Dealer_self", "buy": 31602, "sell": 11497},
        {"date": day, "name": "Dealer_Hedging", "buy": 45050, "sell": 48394},
    ]


class TestFinMindParsing(unittest.TestCase):
    def test_institutional_uses_latest_day_and_twse_definitions(self):
        inst = fc._institutional(_inst_rows())
        self.assertEqual(inst["date"], "2026-11-17")
        self.assertEqual(inst["foreign"], 782755 - 900552)  # excludes Foreign_Dealer_Self
        self.assertEqual(inst["trust"], 197235 - 51715)
        self.assertEqual(inst["dealer"], (31602 - 11497) + (45050 - 48394))
        self.assertEqual(inst["total"], inst["foreign"] + 2000 + inst["trust"] + inst["dealer"])

    def test_institutional_returns_none_when_names_do_not_match(self):
        rows = [{"date": "2026-11-17", "name": "Renamed_Field", "buy": 5, "sell": 1}]
        self.assertIsNone(fc._institutional(rows))

    def test_institutional_returns_none_for_partial_day(self):
        rows = [r for r in _inst_rows() if r["name"] != "Investment_Trust"]
        self.assertIsNone(fc._institutional(rows))

    def test_margin_change(self):
        rows = [{
            "date": "2026-11-17", "MarginPurchaseTodayBalance": 728, "MarginPurchaseYesterdayBalance": 779,
            "ShortSaleTodayBalance": 5, "ShortSaleYesterdayBalance": 14,
        }]
        self.assertEqual(
            fc._margin(rows),
            {"date": "2026-11-17", "margin": 728, "margin_change": -51, "short": 5, "short_change": -9},
        )

    def test_margin_bad_fields_returns_none(self):
        self.assertIsNone(fc._margin([{"date": "2026-11-17", "Other": 1}]))

    def test_get_tw_chips_caches_per_stock_and_day(self):
        fc._get_tw_chips_cached.cache_clear()
        with mock.patch.object(fc, "_fetch", return_value=[]) as fetch:
            fc.get_tw_chips("6223.TWO", today=date(2026, 11, 17))
            fc.get_tw_chips("6223.TWO", today=date(2026, 11, 17))
        self.assertEqual(fetch.call_count, 2)  # one call per dataset, second lookup cached
        self.assertIsNone(fc.get_tw_chips("MU"))

    def test_fetch_errors_are_caught(self):
        fc._get_tw_chips_cached.cache_clear()
        with mock.patch.object(fc, "_fetch", side_effect=ValueError("not json")):
            self.assertEqual(
                fc.get_tw_chips("2303.TW", today=date(2026, 11, 18)),
                {"institutional": None, "margin": None},
            )


class TestCompactFlowLine(unittest.TestCase):
    def setUp(self):
        self._today = cr._taipei_today
        cr._taipei_today = lambda: date(2026, 11, 17)

    def tearDown(self):
        cr._taipei_today = self._today

    @staticmethod
    def _blocks(day):
        return {
            "institution_status": "ok",
            "institution": {"date": day, "foreign_net": 10_000_000, "trust_net": 0,
                            "dealer_net": 2_000, "total_net": 10_002_000},
        }

    @staticmethod
    def _chips(day):
        return {"institutional": {"date": day, "foreign": -5_000, "trust": 1_000, "dealer": 0, "total": -4_000}}

    def test_newer_twse_wins_over_stale_finmind(self):
        line = cr._flow_line(self._chips("2026-11-16"), self._blocks("20261117"))
        self.assertIn("（11/17）", line)
        self.assertIn("外资 +10,000 张", line)

    def test_newer_finmind_wins_over_stale_twse(self):
        line = cr._flow_line(self._chips("2026-11-17"), self._blocks("20261116"))
        self.assertIn("外资 -5 张", line)
        self.assertNotIn("非当日", line)

    def test_same_day_tie_prefers_twse(self):
        line = cr._flow_line(self._chips("2026-11-17"), self._blocks("20261117"))
        self.assertIn("外资 +10,000 张", line)

    def test_stale_only_source_is_marked(self):
        line = cr._flow_line(self._chips("2026-11-14"), {})
        self.assertIn("（11/14，非当日）", line)

    def test_no_sources(self):
        self.assertIsNone(cr._flow_line(None, {}))

    def test_small_flows_never_show_minus_zero_lots(self):
        self.assertEqual(cr._fmt_lots(-400), "-400 股")
        self.assertEqual(cr._fmt_lots(0), "0 张")
        self.assertEqual(cr._fmt_lots(1_500), "+2 张")


if __name__ == "__main__":
    unittest.main()
