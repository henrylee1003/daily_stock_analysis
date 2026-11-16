# -*- coding: utf-8 -*-
"""Compact per-stock report for phone push (REPORT_COMPACT=true).

Each stock shows only: signal + one-line conclusion, the user's own position
and advice (stop-loss wording removed), an earnings summary when results were
published today or on the previous weekday, and Taiwan institutional flows.
"""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.manual_holdings import get_manual_holding

logger = logging.getLogger(__name__)

_STOP_LOSS_RE = re.compile(r"止损|停损|止損|停損")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[，,；;。])")


def compact_report_enabled() -> bool:
    return os.getenv("REPORT_COMPACT", "").strip().lower() in ("1", "true", "yes")


def _taipei_today() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Taipei")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=8)).date()


def _recent_days(today: date) -> set:
    """Today plus the previous weekday (Monday -> Friday)."""
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return {today, prev}


def _yf_symbol(code: str) -> str:
    value = str(code or "").strip().upper()
    if value.isdigit():
        return f"{value}.TW"
    return value


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_recent_earnings(code: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Return the earnings release if it was published today or the previous weekday."""
    today = today or _taipei_today()
    try:
        import yfinance as yf

        frame = yf.Ticker(_yf_symbol(code)).get_earnings_dates(limit=6)
    except Exception as e:
        logger.info("Earnings date lookup failed for %s: %s", code, e)
        return None
    if frame is None or getattr(frame, "empty", True):
        return None
    allowed = _recent_days(today)
    for ts, row in frame.iterrows():
        try:
            day = ts.tz_convert("Asia/Taipei").date() if ts.tzinfo else ts.date()
        except Exception:
            continue
        reported = _finite(row.get("Reported EPS"))
        if day not in allowed or reported is None:
            continue
        return {
            "date": day,
            "reported_eps": reported,
            "estimate_eps": _finite(row.get("EPS Estimate")),
            "surprise_pct": _finite(row.get("Surprise(%)")),
        }
    return None


def _drop_stop_loss(text: str) -> str:
    """Remove clauses that talk about stop-loss levels."""
    parts = [p for p in _CLAUSE_SPLIT_RE.split(str(text or "")) if p.strip()]
    kept = [p for p in parts if not _STOP_LOSS_RE.search(p)]
    result = "".join(kept).strip().rstrip("，,；;")
    return result


_ADVICE_PREFIX_RE = re.compile(r"^[^：:]{0,20}(持仓|持股|持有)[^：:]{0,20}[：:]")


def _first_sentence(text: str) -> str:
    """Keep only the first sentence (up to the first 。！？)."""
    text = str(text or "").strip()
    match = re.search(r"[。！？!?]", text)
    return text[: match.end()] if match else text


def _short_advice(text: str) -> str:
    """Drop the "持仓者（成本…）：" prefix, stop-loss clauses, keep the first sentence."""
    text = _ADVICE_PREFIX_RE.sub("", str(text or "").strip(), count=1)
    return _first_sentence(_drop_stop_loss(text))


def _fmt_num(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _holding_tag(code: str, price: Optional[float]) -> Optional[str]:
    """Short P&L tag like "持股 -21.85%" (or "持股" when no price)."""
    holding = get_manual_holding(code)
    if not holding:
        return None
    price = _finite(price)
    cost = holding["avg_cost"]
    if price and cost > 0:
        return f"持股 {(price / cost - 1) * 100:+.2f}%"
    return "持股"


def _earnings_lines(notifier: Any, result: Any, blocks: Dict[str, Any]) -> List[str]:
    earnings = fetch_recent_earnings(result.code)
    if not earnings:
        return []
    head = f"📊 财报（{earnings['date'].strftime('%m/%d')} 公布）：EPS {_fmt_num(earnings['reported_eps'])}"
    if earnings["estimate_eps"] is not None:
        head += f"，预估 {_fmt_num(earnings['estimate_eps'])}"
    surprise = earnings["surprise_pct"]
    if surprise is not None:
        head += f"，{'优于' if surprise >= 0 else '低于'}预期 {surprise:+.1f}%"
    lines = [head]
    growth = blocks.get("growth") or {}
    yoy_parts = []
    if _finite(growth.get("revenue_yoy")) is not None:
        yoy_parts.append(f"营收年增 {notifier._format_percent(growth.get('revenue_yoy'))}")
    if _finite(growth.get("net_profit_yoy")) is not None:
        yoy_parts.append(f"净利年增 {notifier._format_percent(growth.get('net_profit_yoy'))}")
    if yoy_parts:
        lines.append("　" + "｜".join(yoy_parts))
    intel = (result.dashboard or {}).get("intelligence") or {}
    outlook = str(intel.get("earnings_outlook") or "").strip()
    if outlook:
        lines.append(f"　结论：{outlook}")
    return lines


def _fmt_lots(value: Any) -> Optional[str]:
    shares = _finite(value)
    if shares is None:
        return None
    return f"{shares / 1000:+,.0f} 张"


def _flow_line(notifier: Any, blocks: Dict[str, Any]) -> Optional[str]:
    """Taiwan institutional net buy/sell in lots, e.g. 外资 +10,018 张."""
    if blocks.get("institution_status") != "ok":
        return None
    inst = blocks.get("institution") or {}
    parts = []
    for label, key in (("外资", "foreign_net"), ("投信", "trust_net"), ("自营商", "dealer_net"), ("合计", "total_net")):
        lots = _fmt_lots(inst.get(key))
        if lots:
            parts.append(f"{label} {lots}")
    if not parts:
        return None
    raw_date = str(inst.get("date") or "")
    note = ""
    if len(raw_date) == 8 and raw_date.isdigit():
        note = f"（{raw_date[4:6]}/{raw_date[6:8]}"
        if raw_date != _taipei_today().strftime("%Y%m%d"):
            note += "，非当日"
        note += "）"
    return f"💰 三大法人{note}：" + "｜".join(parts)


def generate_compact_report(notifier: Any, results: List[Any], report_date: Optional[str] = None) -> str:
    report_date = report_date or datetime.now().strftime("%Y-%m-%d")
    report_language = notifier._get_report_language(results)
    lines = [f"📋 {report_date} 持股快报"]
    if not results:
        return "\n".join(lines + ["", "今日无分析结果"])
    buy_count, sell_count, hold_count = notifier._count_display_decisions(results, report_language)
    lines.append(f"共 {len(results)} 档｜🟢{buy_count} 🟡{hold_count} 🔴{sell_count}")
    notifier._append_market_status_line(lines, results, report_language)

    for result in sorted(results, key=lambda r: r.sentiment_score, reverse=True):
        signal_text, emoji, _ = notifier._get_signal_level(result)
        name = notifier._get_display_name(result, report_language)
        dash = result.dashboard or {}
        core = dash.get("core_conclusion") or {}
        one = str(core.get("one_sentence") or result.analysis_summary or "").strip()

        header = f"{emoji} {name}（{result.code}）｜{signal_text}｜评分 {result.sentiment_score}"
        tag = _holding_tag(result.code, getattr(result, "current_price", None))
        if tag:
            header += f"｜{tag}"
        lines += ["", header]
        if one:
            lines.append(f"结论：{_first_sentence(_drop_stop_loss(one))}")
        if tag:
            advice = _short_advice((core.get("position_advice") or {}).get("has_position") or "")
            if advice:
                lines.append(f"建议：{advice}")

        blocks = notifier._get_fundamental_blocks(result)
        lines += _earnings_lines(notifier, result, blocks)
        flow = _flow_line(notifier, blocks)
        if flow:
            lines.append(flow)

    lines += ["", f"产生时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    models = notifier._collect_models_used(results)
    if models:
        lines.append(f"分析模型：{', '.join(models)}")
    return "\n".join(lines)
