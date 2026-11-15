# -*- coding: utf-8 -*-
"""Manual holdings from the PORTFOLIO_HOLDINGS env var.

Format: ``CODE:QUANTITY:AVG_COST`` separated by commas, e.g.
``2303.TW:600:142.25,6223.TWO:19:5225.26,MU:2:995.975``.

Used to give the LLM the user's own position (shares + average cost) so the
report can include position-aware advice. Keep this value in a GitHub Secret.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ENV_NAME = "PORTFOLIO_HOLDINGS"
_STRIP_SUFFIXES = (".TWO", ".TW", ".US")


def _normalize(code: str) -> str:
    """Normalize a code for matching: upper-case, drop market prefix/suffix."""
    value = str(code or "").strip().upper()
    for prefix in ("US.", "TW."):
        if value.startswith(prefix):
            value = value[len(prefix):]
    for suffix in _STRIP_SUFFIXES:
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value


def parse_manual_holdings(raw: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """Parse the env value into {normalized_code: {symbol, quantity, avg_cost}}."""
    holdings: Dict[str, Dict[str, Any]] = {}
    for entry in str(raw or "").replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) != 3:
            logger.warning("PORTFOLIO_HOLDINGS entry skipped (need CODE:QTY:COST): %s", parts[0] if parts else "")
            continue
        symbol, qty_text, cost_text = parts
        try:
            quantity = float(qty_text.replace("_", ""))
            avg_cost = float(cost_text.replace("_", ""))
        except ValueError:
            logger.warning("PORTFOLIO_HOLDINGS entry skipped (bad number): %s", symbol)
            continue
        if not (math.isfinite(quantity) and math.isfinite(avg_cost)):
            continue
        holdings[_normalize(symbol)] = {
            "symbol": symbol.upper(),
            "quantity": quantity,
            "avg_cost": avg_cost,
            "total_cost": round(quantity * avg_cost, 4),
            "cost_method": "manual",
        }
    return holdings


def get_manual_holding(code: str) -> Optional[Dict[str, Any]]:
    """Return a portfolio_context dict for ``code`` from PORTFOLIO_HOLDINGS, if any."""
    raw = os.getenv(_ENV_NAME, "")
    if not raw.strip():
        return None
    holding = parse_manual_holdings(raw).get(_normalize(code))
    return dict(holding) if holding else None


def _fmt(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def format_holding_prompt_section(
    portfolio_context: Optional[Dict[str, Any]],
    current_price: Optional[float] = None,
    *,
    english: bool = False,
) -> str:
    """Render the user's own position as a prompt section; empty if no data."""
    if not isinstance(portfolio_context, dict):
        return ""
    try:
        quantity = float(portfolio_context.get("quantity"))
        avg_cost = float(portfolio_context.get("avg_cost"))
    except (TypeError, ValueError):
        return ""
    if quantity <= 0 or avg_cost <= 0:
        return ""

    pnl_line = ""
    try:
        price = float(current_price) if current_price is not None else None
    except (TypeError, ValueError):
        price = None
    if price and price > 0 and math.isfinite(price):
        pnl = (price - avg_cost) * quantity
        pnl_pct = (price / avg_cost - 1) * 100
        if english:
            pnl_line = f"- Latest price {_fmt(price)}; unrealized P&L {pnl:+,.2f} ({pnl_pct:+.2f}%)\n"
        else:
            pnl_line = f"- 最新价 {_fmt(price)}；未实现损益 {pnl:+,.2f}（{pnl_pct:+.2f}%）\n"

    if english:
        return (
            "\n## 💼 User's Own Position (actually held)\n"
            f"- Shares held: {_fmt(quantity)}\n"
            f"- Average cost: {_fmt(avg_cost)}\n"
            f"{pnl_line}"
            "- Requirement: the user already holds this stock. Give concrete advice for THIS position "
            "(hold / add / trim / stop-loss level), referencing the average cost.\n"
        )
    return (
        "\n## 💼 用户实际持仓（已持有）\n"
        f"- 持有股数：{_fmt(quantity)}\n"
        f"- 成本均价：{_fmt(avg_cost)}\n"
        f"{pnl_line}"
        "- 要求：用户已经持有这档股票。请针对“这笔持仓”给出具体建议（续抱／加码／减码／停损价位），"
        "并以成本均价为参考说明理由。\n"
    )
