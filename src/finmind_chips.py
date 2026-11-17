# -*- coding: utf-8 -*-
# Usage: from src.finmind_chips import get_tw_chips; get_tw_chips("6223.TWO")
# Description: Taiwan chip data (institutional flows + margin trading) from the FinMind API,
#              for both TWSE (.TW) and TPEx (.TWO) stocks. Results are cached per (code, day).
# Input: Taiwan stock code with .TW / .TWO suffix; optional env FINMIND_TOKEN
# Output: {"institutional": {date, foreign, trust, dealer, total} (shares) | None,
#          "margin": {date, margin, margin_change, short, short_change} (lots) | None}
# Dependencies: requests (already in requirements.txt)
"""Taiwan chip data from FinMind.

``foreign`` follows the TWSE T86 definition (外陸資, excluding 外資自營商) so it
matches the TWSE fallback; ``total`` includes every investor type like T86's
三大法人合計. FINMIND_TOKEN is optional; without it FinMind allows a smaller
hourly quota, enough for a few stocks.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional

from src.lookup_backoff import failed_recently, mark_failed

logger = logging.getLogger(__name__)

_API_URL = "https://api.finmindtrade.com/api/v4/data"
_FOREIGN = ("Foreign_Investor",)
_FOREIGN_DEALER = ("Foreign_Dealer_Self",)
_TRUST = ("Investment_Trust",)
_DEALER = ("Dealer_self", "Dealer_Hedging")


def tw_stock_id(code: str) -> Optional[str]:
    """'2303.TW' / '6223.TWO' / 'TW.2303' -> '2303' / '6223' / '2303'; None for non-Taiwan codes."""
    from src.services.market_symbol_utils import is_tw_suffix_symbol, split_suffix_symbol

    value = str(code or "").strip().upper()
    if value.startswith("TW.") and value[3:].isdigit():
        return value[3:]
    if is_tw_suffix_symbol(value):
        return split_suffix_symbol(value)[0]
    return None


def _fetch(dataset: str, stock_id: str, start: date) -> List[Dict[str, Any]]:
    import requests

    params = {"dataset": dataset, "data_id": stock_id, "start_date": start.isoformat()}
    headers = {}
    token = os.getenv("FINMIND_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(_API_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} status={payload.get('status')} msg={payload.get('msg')}")
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _institutional(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Net buy/sell in shares for the newest date with complete rows.

    A partially published latest day falls back to the previous complete day
    (shown with its own date); None when no day is complete.
    """
    for day in sorted({str(r.get("date") or "") for r in rows}, reverse=True):
        if not day:
            continue
        result = _institutional_for_day(rows, day)
        if result:
            return result
    return None


def _institutional_for_day(rows: List[Dict[str, Any]], latest: str) -> Optional[Dict[str, Any]]:
    net = {"foreign": 0.0, "trust": 0.0, "dealer": 0.0, "foreign_dealer": 0.0}
    matched = set()
    for row in rows:
        if str(row.get("date")) != latest:
            continue
        name = row.get("name")
        try:
            diff = float(row.get("buy") or 0) - float(row.get("sell") or 0)
        except (TypeError, ValueError):
            continue
        if name in _FOREIGN:
            net["foreign"] += diff
            matched.add("foreign")
        elif name in _FOREIGN_DEALER:
            net["foreign_dealer"] += diff
        elif name in _TRUST:
            net["trust"] += diff
            matched.add("trust")
        elif name in _DEALER:
            net["dealer"] += diff
            matched.add("dealer")
    # Partial or renamed data must not be shown as real zeros
    if matched != {"foreign", "trust", "dealer"}:
        logger.warning("FinMind institutional rows incomplete for %s (matched=%s)", latest, sorted(matched))
        return None
    total = net["foreign"] + net["foreign_dealer"] + net["trust"] + net["dealer"]
    return {
        "date": latest,
        "foreign": net["foreign"],
        "trust": net["trust"],
        "dealer": net["dealer"],
        "total": total,
    }


def _margin(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Margin purchase / short sale balances (lots) and daily change for the latest date."""
    if not rows:
        return None
    row = max(rows, key=lambda r: str(r.get("date") or ""))
    try:
        margin = int(row["MarginPurchaseTodayBalance"])
        margin_prev = int(row["MarginPurchaseYesterdayBalance"])
        short = int(row["ShortSaleTodayBalance"])
        short_prev = int(row["ShortSaleYesterdayBalance"])
    except (KeyError, TypeError, ValueError):
        logger.warning("FinMind margin row has unexpected fields: %s", sorted(row.keys()))
        return None
    return {
        "date": str(row.get("date")),
        "margin": margin,
        "margin_change": margin - margin_prev,
        "short": short,
        "short_change": short - short_prev,
    }


class _NothingFetched(Exception):
    """Raised inside the cached function so lru_cache does not keep a failed lookup."""


@lru_cache(maxsize=64)
def _get_tw_chips_cached(stock_id: str, day: date) -> Dict[str, Any]:
    start = day - timedelta(days=10)
    result: Dict[str, Any] = {"institutional": None, "margin": None}
    try:
        result["institutional"] = _institutional(
            _fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start)
        )
    except Exception as e:
        logger.warning("FinMind institutional fetch failed for %s: %s", stock_id, e)
    try:
        result["margin"] = _margin(_fetch("TaiwanStockMarginPurchaseShortSale", stock_id, start))
    except Exception as e:
        logger.warning("FinMind margin fetch failed for %s: %s", stock_id, e)
    if result["institutional"] is None and result["margin"] is None:
        raise _NothingFetched(stock_id)
    return result


def get_tw_chips(code: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Return chip data for a Taiwan stock (cached per stock and day), or None for non-TW codes."""
    stock_id = tw_stock_id(code)
    if not stock_id:
        return None
    day = today or date.today()
    key = ("finmind", stock_id, day)
    empty = {"institutional": None, "margin": None}
    if failed_recently(key):
        return empty
    try:
        # Copy so callers cannot mutate the cached dict
        return dict(_get_tw_chips_cached(stock_id, day))
    except _NothingFetched:
        # Skipped for a few minutes, then retried (not cached for the day)
        mark_failed(key)
        return empty
