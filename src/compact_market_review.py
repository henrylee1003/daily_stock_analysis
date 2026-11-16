# -*- coding: utf-8 -*-
"""Compact market review for phone push (REPORT_COMPACT=true).

Turns the long LLM market review into a few lines per market: index moves,
one-line takeaway, strategy, and (Taiwan) market-wide institutional flows
from TWSE BFI82U. Falls back to the original section when parsing fails.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_SHORT_INDEX_NAMES = {
    "标普500指数": "标普",
    "纳斯达克综合指数": "那指",
    "纳斯达克指数": "那指",
    "道琼斯工业指数": "道琼",
    "VIX恐慌指数": "VIX",
    "台湾加权指数": "加权",
    "台股加权指数": "加权",
    "加权指数": "加权",
    "柜买指数": "柜买",
}
_SEPARATOR_MARKERS = ("以下为下一市场", "Next market recap", "다음 시장")
_STRATEGY_KEYS = ("策略结论",)
_POSITION_KEYS = ("仓位建议", "仓位区间", "建议仓位")


def _clean(line: str) -> str:
    """Strip markdown markers from a single line."""
    line = re.sub(r"^[ \t]*(#{1,6}|>|[-*+•])[ \t]*", "", line)
    line = line.replace("**", "").replace("`", "")
    return line.strip()


def _region_of(section: str) -> Optional[str]:
    head = section[:300]
    if "台股" in head or "台湾" in head:
        return "tw"
    if "美股" in head:
        return "us"
    return None


def _index_rows(lines: List[str]) -> List[str]:
    rows: List[str] = []
    header: Optional[List[str]] = None
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            header = None if rows else header
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if header is None:
            if cells and ("指数" in cells[0] or cells[0].lower() == "index"):
                header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        try:
            last = cells[header.index("最新")]
            pct = cells[header.index("涨跌幅")]
        except (ValueError, IndexError):
            continue
        name = _SHORT_INDEX_NAMES.get(cells[0], cells[0])
        rows.append(f"{name} {last} {pct.replace(' ', '')}")
    return rows


def _first_matching(lines: List[str], keys) -> Optional[str]:
    for line in lines:
        text = _clean(line)
        if any(k in text for k in keys):
            return re.sub(r"^.*?[：:]", "", text, count=1).strip() or None
    return None


def _summary(lines: List[str]) -> Optional[str]:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">") and not any(m in stripped for m in _SEPARATOR_MARKERS):
            text = _clean(stripped)
            if text:
                return text
    return None


def _taipei_today() -> date:
    from src.compact_report import _taipei_today as today

    return today()


def fetch_tw_market_flows(today: Optional[date] = None, max_back_days: int = 5) -> Optional[Dict[str, object]]:
    """Fetch TWSE market-wide institutional net buy/sell (NT$) for the latest day with data."""
    try:
        import requests
    except Exception:
        return None
    today = today or _taipei_today()
    for back in range(max_back_days + 1):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        url = (
            "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
            f"?response=json&type=day&dayDate={day.strftime('%Y%m%d')}"
        )
        try:
            payload = requests.get(url, timeout=10).json()
        except Exception as e:
            logger.info("TWSE BFI82U fetch failed for %s: %s", day, e)
            continue
        if payload.get("stat") != "OK" or not payload.get("data"):
            continue
        net: Dict[str, float] = {"foreign": 0.0, "trust": 0.0, "dealer": 0.0, "total": 0.0}
        for row in payload["data"]:
            try:
                name, diff = row[0], float(str(row[3]).replace(",", ""))
            except (IndexError, ValueError):
                continue
            if name.startswith("外資"):
                net["foreign"] += diff
            elif name.startswith("投信"):
                net["trust"] += diff
            elif name.startswith("自營商"):
                net["dealer"] += diff
            elif name.startswith("合計"):
                net["total"] = diff
        return {"date": day, **net}
    return None


def _tw_flow_line(flows: Optional[Dict[str, object]]) -> Optional[str]:
    if not flows:
        return None
    day = flows["date"]
    note = f"（{day.strftime('%m/%d')}"
    if day != _taipei_today():
        note += "，非当日"
    note += "）"

    def yi(value: float) -> str:
        return f"{value / 1e8:+,.1f} 亿"

    return (
        f"💰 三大法人{note}：外资 {yi(flows['foreign'])}｜投信 {yi(flows['trust'])}"
        f"｜自营商 {yi(flows['dealer'])}｜合计 {yi(flows['total'])}"
    )


def _compact_section(section: str) -> Optional[str]:
    region = _region_of(section)
    lines = section.split("\n")
    indices = _index_rows(lines)
    summary = _summary(lines)
    if not indices and not summary:
        return None
    title = {"tw": "🇹🇼 台股大盘", "us": "🇺🇸 美股大盘"}.get(region or "", "📈 大盘")
    out = [title]
    if indices:
        out.append("｜".join(indices))
    if summary:
        out.append(f"重点：{summary}")
    strategy = _first_matching(lines, _STRATEGY_KEYS)
    position = _first_matching(lines, _POSITION_KEYS)
    if strategy or position:
        out.append("策略：" + "，".join(p.rstrip("。") for p in (strategy, position) if p))
    if region == "tw":
        flow = _tw_flow_line(fetch_tw_market_flows())
        if flow:
            out.append(flow)
    return "\n".join(out)


def compact_market_review(report: str) -> str:
    """Return a compact version of the full market review; keep the original on failure."""
    try:
        sections = re.split(r"\n[ \t]*-{3,}[ \t]*\n", str(report or ""))
        compact_parts: List[str] = []
        for section in sections:
            if not section.strip():
                continue
            compact = _compact_section(section)
            if compact is None:
                # Separator-only chunks carry nothing useful; anything else is kept as-is
                if any(m in section for m in _SEPARATOR_MARKERS) and len(section.strip()) < 40:
                    continue
                compact_parts.append(section.strip())
            else:
                compact_parts.append(compact)
        return "\n\n──────────\n\n".join(compact_parts) if compact_parts else report
    except Exception as e:
        logger.warning("Compact market review failed, sending full text: %s", e)
        return report
