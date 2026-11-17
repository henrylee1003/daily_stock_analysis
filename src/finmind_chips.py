# -*- coding: utf-8 -*-
"""Taiwan chip data (institutional flows + margin trading) from the FinMind API.

Covers both TWSE (.TW) and TPEx (.TWO) stocks. FINMIND_TOKEN is optional;
without it FinMind allows a smaller hourly quota, enough for a few stocks.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_API_URL = "https://api.finmindtrade.com/api/v4/data"
_FOREIGN = ("Foreign_Investor", "Foreign_Dealer_Self")
_TRUST = ("Investment_Trust",)
_DEALER = ("Dealer_self", "Dealer_Hedging")


def tw_stock_id(code: str) -> Optional[str]:
    """'2303.TW' / '6223.TWO' -> '2303' / '6223'; None for non-Taiwan codes."""
    value = str(code or "").strip().upper()
    for suffix in (".TWO", ".TW"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return None


def _fetch(dataset: str, stock_id: str, start: date) -> List[Dict[str, Any]]:
    import requests

    params = {"dataset": dataset, "data_id": stock_id, "start_date": start.isoformat()}
    headers = {}
    token = os.getenv("FINMIND_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(_API_URL, params=params, headers=headers, timeout=15)
    payload = resp.json()
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} status={payload.get('status')} msg={payload.get('msg')}")
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _institutional(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Net buy/sell in shares for the latest date."""
    if not rows:
        return None
    latest = max(str(r.get("date") or "") for r in rows)
    net = {"foreign": 0.0, "trust": 0.0, "dealer": 0.0}
    for row in rows:
        if str(row.get("date")) != latest:
            continue
        diff = float(row.get("buy") or 0) - float(row.get("sell") or 0)
        name = row.get("name")
        if name in _FOREIGN:
            net["foreign"] += diff
        elif name in _TRUST:
            net["trust"] += diff
        elif name in _DEALER:
            net["dealer"] += diff
    net["total"] = net["foreign"] + net["trust"] + net["dealer"]
    return {"date": latest, **net}


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
        return None
    return {
        "date": str(row.get("date")),
        "margin": margin,
        "margin_change": margin - margin_prev,
        "short": short,
        "short_change": short - short_prev,
    }


def get_tw_chips(code: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Return {'institutional': {...}|None, 'margin': {...}|None} or None for non-TW codes."""
    stock_id = tw_stock_id(code)
    if not stock_id:
        return None
    start = (today or date.today()) - timedelta(days=10)
    result: Dict[str, Any] = {"institutional": None, "margin": None}
    try:
        result["institutional"] = _institutional(
            _fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start)
        )
    except Exception as e:
        logger.info("FinMind institutional fetch failed for %s: %s", stock_id, e)
    try:
        result["margin"] = _margin(_fetch("TaiwanStockMarginPurchaseShortSale", stock_id, start))
    except Exception as e:
        logger.info("FinMind margin fetch failed for %s: %s", stock_id, e)
    return result
