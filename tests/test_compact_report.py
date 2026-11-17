# -*- coding: utf-8 -*-
# Usage: python -m pytest tests/test_compact_report.py -q
# Description: Tests for compact report helpers, manual holdings and compact market review
# Input: None (network calls are mocked)
# Output: pytest results
# Dependencies: pytest
"""Tests for src.compact_report, src.manual_holdings and src.compact_market_review."""

import os
import unittest
from datetime import date
from unittest import mock

import src.compact_market_review as cmr
import src.compact_report as cr
from src.env_flags import env_flag
from src.manual_holdings import format_holding_prompt_section, get_manual_holding


class TestStopLossFilter(unittest.TestCase):
    def test_thousands_separator_is_not_split(self):
        text = "若跌破5,100元则止损，可续抱。"
        self.assertEqual(cr._drop_stop_loss(text), "可续抱。")

    def test_price_in_kept_clause_stays_intact(self):
        text = "反弹至5,225元附近可减码，跌破4,000元止损。"
        self.assertEqual(cr._drop_stop_loss(text), "反弹至5,225元附近可减码")

    def test_ascii_comma_between_words_still_splits(self):
        self.assertEqual(cr._drop_stop_loss("续抱,设止损"), "续抱")

    def test_short_advice_drops_prefix_and_keeps_first_sentence(self):
        text = "持仓者（成本995.98元）：暂持观望，严禁补仓。若下破760元需执行止损。"
        self.assertEqual(cr._short_advice(text), "暂持观望，严禁补仓。")


class TestEarningsSymbol(unittest.TestCase):
    def test_bare_digits_are_not_guessed_as_taiwan(self):
        self.assertIsNone(cr._yf_symbol("600519"))
        self.assertIsNone(cr.fetch_recent_earnings("600519", today=date(2026, 11, 17)))

    def test_suffixed_and_us_codes_pass_through(self):
        self.assertEqual(cr._yf_symbol("6223.two"), "6223.TWO")
        self.assertEqual(cr._yf_symbol("MU"), "MU")

    def test_earnings_lookup_is_cached_per_symbol_and_day(self):
        cr._fetch_recent_earnings_cached.cache_clear()
        fake_yf = mock.MagicMock()
        fake_yf.Ticker.return_value.get_earnings_dates.return_value = None
        with mock.patch.dict("sys.modules", {"yfinance": fake_yf}):
            cr.fetch_recent_earnings("MU", today=date(2026, 11, 17))
            cr.fetch_recent_earnings("MU", today=date(2026, 11, 17))
        self.assertEqual(fake_yf.Ticker.call_count, 1)


class TestManualHoldings(unittest.TestCase):
    def test_sold_out_position_is_ignored_everywhere(self):
        with mock.patch.dict(os.environ, {"PORTFOLIO_HOLDINGS": "MU:0:995.975,2303.TW:600:142.25"}):
            self.assertIsNone(get_manual_holding("MU"))
            self.assertIsNone(cr._holding_tag("MU", 778.31))
            self.assertEqual(cr._holding_tag("2303.TW", 103.0), "持股 -27.59%")

    def test_prompt_asks_for_no_stop_loss(self):
        text = format_holding_prompt_section({"quantity": 600, "avg_cost": 142.25}, 103.0)
        self.assertIn("不要提停损价位", text)
        self.assertNotIn("停损价位）", text)


class TestEnvFlag(unittest.TestCase):
    def test_values(self):
        for value, expected in (("true", True), ("YES", True), ("1", True), ("false", False), ("", False)):
            with mock.patch.dict(os.environ, {"X_FLAG": value}):
                self.assertEqual(env_flag("X_FLAG"), expected, value)


class TestCompactMarketFlows(unittest.TestCase):
    def setUp(self):
        self._today = cr._taipei_today
        cr._taipei_today = lambda: date(2026, 11, 17)
        cmr._fetch_tw_market_flows_cached.cache_clear()

    def tearDown(self):
        cr._taipei_today = self._today
        cmr._fetch_tw_market_flows_cached.cache_clear()

    def test_market_flows_use_same_foreign_definition_and_shared_format(self):
        payload = {"stat": "OK", "data": [
            ["自營商(自行買賣)", "0", "0", "100,000,000"],
            ["自營商(避險)", "0", "0", "50,000,000"],
            ["投信", "0", "0", "200,000,000"],
            ["外資及陸資(不含外資自營商)", "0", "0", "1,000,000,000"],
            ["外資自營商", "0", "0", "30,000,000"],
            ["合計", "0", "0", "1,380,000,000"],
        ]}
        resp = mock.MagicMock()
        resp.json.return_value = payload
        with mock.patch("requests.get", return_value=resp) as get:
            flows = cmr.fetch_tw_market_flows()
            cmr.fetch_tw_market_flows()
        self.assertEqual(get.call_count, 1)  # cached per day
        self.assertEqual(flows["foreign"], 1_000_000_000)  # excludes 外資自營商
        self.assertEqual(flows["total"], 1_380_000_000)
        line = cmr._tw_flow_line(flows)
        self.assertEqual(
            line, "💰 三大法人（11/17）：外资 +10.0 亿｜投信 +2.0 亿｜自营商 +1.5 亿｜合计 +13.8 亿"
        )

    def test_maybe_compact_respects_switch(self):
        text = "# 美股大盘复盘\n\n> 重点一句。\n"
        with mock.patch.dict(os.environ, {"REPORT_COMPACT": "false"}):
            self.assertEqual(cmr.maybe_compact_market_report(text), text)
        with mock.patch.dict(os.environ, {"REPORT_COMPACT": "true"}):
            self.assertIn("重点：重点一句。", cmr.maybe_compact_market_report(text))


if __name__ == "__main__":
    unittest.main()
