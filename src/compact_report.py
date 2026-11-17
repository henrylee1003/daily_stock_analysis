# -*- coding: utf-8 -*-
# Usage: from src.compact_report import generate_compact_report (called by NotificationService when REPORT_COMPACT=true)
# Description: Short per-stock phone report: conclusion, own position, advice, recent earnings, TW chips
# Input: NotificationService instance + list of AnalysisResult; env PORTFOLIO_HOLDINGS, REPORT_COMPACT
# Output: Markdown string
# Dependencies: yfinance, requests (already in requirements.txt)
"""Compact per-stock report for phone push (REPORT_COMPACT=true).

Each stock shows only: signal + one-line conclusion, the user's own position
and advice (stop-loss wording removed), an earnings summary when results were
published today or on the previous weekday, and Taiwan institutional flows.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional

from src.env_flags import env_flag
from src.finmind_chips import get_tw_chips
from src.manual_holdings import get_manual_holding

logger = logging.getLogger(__name__)

_STOP_LOSS_RE = re.compile(r"止损|停损|止損|停損")
# Split after clause punctuation; an ASCII comma followed by a digit is a
# thousands separator (e.g. 5,100) and must not split the number
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[，；;。])|(?<=,)(?!\d)")


def compact_report_enabled() -> bool:
    return env_flag("REPORT_COMPACT")


def _taipei_now() -> datetime:
    """Runner clocks are UTC; every date/time the user sees is Taipei time."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        return datetime.utcnow() + timedelta(hours=8)


def _taipei_today() -> date:
    return _taipei_now().date()


def _recent_days(today: date) -> set:
    """Today plus the previous weekday (Monday -> Friday)."""
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return {today, prev}


def _yf_symbol(code: str) -> Optional[str]:
    """Yahoo symbol for earnings lookup; None for bare digits (A-share codes in this project)."""
    value = str(code or "").strip().upper()
    if value.startswith("US."):
        value = value[3:]
    elif value.startswith("TW.") and value[3:].isdigit():
        value = f"{value[3:]}.TW"
    if not value or value.isdigit():
        return None
    return value


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_recent_earnings(code: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Return the earnings release if it was published today or the previous weekday."""
    symbol = _yf_symbol(code)
    if not symbol:
        return None
    # The report is built several times per run; cache per (symbol, day)
    return _fetch_recent_earnings_cached(symbol, today or _taipei_today())


@lru_cache(maxsize=64)
def _fetch_recent_earnings_cached(symbol: str, today: date) -> Optional[Dict[str, Any]]:
    try:
        import yfinance as yf

        frame = yf.Ticker(symbol).get_earnings_dates(limit=6)
    except Exception as e:
        logger.info("Earnings date lookup failed for %s: %s", symbol, e)
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
    """Shares -> lots (1 张 = 1000 股); under one lot keeps shares so it never shows "-0 张"."""
    shares = _finite(value)
    if shares is None:
        return None
    if shares == 0:
        return "0 张"
    if abs(shares) < 1000:
        return f"{shares:+,.0f} 股"
    return f"{shares / 1000:+,.0f} 张"


def _iso_date(raw: Any) -> str:
    """'20261117' or '2026-11-17' -> '2026-11-17'; '' when unrecognized."""
    text = str(raw or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return ""


def _date_note(raw_date: Any) -> str:
    """Date -> '（11/17）', adding '，非当日' when it is not today (Taipei)."""
    iso_date = _iso_date(raw_date)
    if not iso_date:
        return ""
    note = f"（{iso_date[5:7]}/{iso_date[8:10]}"
    if iso_date != _taipei_today().isoformat():
        note += "，非当日"
    return note + "）"


def _finmind_flows(chips: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    inst = (chips or {}).get("institutional")
    if not inst or not _iso_date(inst.get("date")):
        return None
    return {"date": _iso_date(inst["date"]), **{k: inst.get(k) for k in ("foreign", "trust", "dealer", "total")}}


def _twse_flows(blocks: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if blocks.get("institution_status") != "ok":
        return None
    inst = blocks.get("institution") or {}
    flows = {
        "foreign": inst.get("foreign_net"),
        "trust": inst.get("trust_net"),
        "dealer": inst.get("dealer_net"),
        "total": inst.get("total_net"),
    }
    if all(_finite(v) is None for v in flows.values()):
        return None
    return {"date": _iso_date(inst.get("date")), **flows}


def _flow_line(chips: Optional[Dict[str, Any]], blocks: Dict[str, Any]) -> Optional[str]:
    """Institutional net buy/sell; uses whichever source (FinMind / TWSE) has the newer date."""
    candidates = [f for f in (_twse_flows(blocks), _finmind_flows(chips)) if f]
    if not candidates:
        return None
    # max() keeps the first on ties, so the official TWSE block wins a same-day tie
    flows = max(candidates, key=lambda f: f["date"])
    return format_flow_line(flows, _fmt_lots)


_FLOW_LABELS = (("外资", "foreign"), ("投信", "trust"), ("自营商", "dealer"), ("合计", "total"))


def format_flow_line(flows: Dict[str, Any], fmt) -> Optional[str]:
    """Shared "💰 三大法人（MM/DD）：外资 …｜投信 …｜自营商 …｜合计 …" line (stocks and market)."""
    parts = []
    for label, key in _FLOW_LABELS:
        text = fmt(flows.get(key))
        if text:
            parts.append(f"{label} {text}")
    if not parts:
        return None
    return f"💰 三大法人{_date_note(flows.get('date'))}：" + "｜".join(parts)


def _margin_line(chips: Optional[Dict[str, Any]]) -> Optional[str]:
    """Margin purchase / short sale balance in lots with daily change."""
    margin = (chips or {}).get("margin")
    if not margin:
        return None
    return (
        f"📒 融资融券{_date_note(margin['date'])}："
        f"融资 {margin['margin']:,} 张（{margin['margin_change']:+,}）｜"
        f"融券 {margin['short']:,} 张（{margin['short_change']:+,}）"
    )


def generate_compact_report(notifier: Any, results: List[Any], report_date: Optional[str] = None) -> str:
    report_date = report_date or _taipei_now().strftime("%Y-%m-%d")
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
        chips = get_tw_chips(result.code, today=_taipei_today())
        flow = _flow_line(chips, blocks)
        if flow:
            lines.append(flow)
        margin = _margin_line(chips)
        if margin:
            lines.append(margin)

    lines += ["", f"产生时间：{_taipei_now().strftime('%Y-%m-%d %H:%M')}"]
    models = notifier._collect_models_used(results)
    if models:
        lines.append(f"分析模型：{', '.join(models)}")
    return "\n".join(lines)
