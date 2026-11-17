# -*- coding: utf-8 -*-
# Usage: from src.traditional_chinese import to_traditional_chinese; to_traditional_chinese(text)
# Description: Simplified -> Taiwan Traditional Chinese with Taiwan investing terms
# Input: Text; env REPORT_TRADITIONAL_CHINESE=true to enable
# Output: Converted text (original text on error)
# Dependencies: pip install opencc-python-reimplemented
"""Optional Simplified -> Taiwan Traditional Chinese conversion for outgoing messages."""

import logging
import re

from src.env_flags import env_flag

logger = logging.getLogger(__name__)


_OPENCC_CONVERTER = None

# Mainland investing terms (after OpenCC) -> Taiwan usage. Longer terms first.
TW_INVESTING_TERMS = (
    ("覆盤", "復盤"),
    ("臺", "台"),
    ("止損位", "停損價"),
    ("止損", "停損"),
    ("止盈", "停利"),
    ("止利", "停利"),
    ("市盈率", "本益比"),
    ("市淨率", "股價淨值比"),
    ("股息率", "殖利率"),
    ("歸母淨利潤", "稅後淨利"),
    ("營收同比", "營收年增率"),
    ("淨利同比", "淨利年增率"),
    ("同比", "年增"),
    ("環比", "較上期"),
    ("分紅", "配息"),
    ("倉位建議", "持股比重建議"),
    ("建議倉位", "建議持股比重"),
    ("空倉者", "空手者"),
    ("持倉者", "持股者"),
    ("建倉", "進場"),
    ("加倉", "加碼"),
    ("減倉", "減碼"),
    ("補倉", "攤平"),
    ("清倉", "出清"),
    ("重倉", "重壓"),
    ("空倉", "空手"),
    ("持倉", "持股"),
    ("倉位", "持股比重"),
    ("拋壓", "賣壓"),
    ("利好", "利多"),
    ("回撥", "回檔"),
    ("執行在", "運行在"),
    ("成交額", "成交金額"),
)

# Short terms that are also the start of unrelated words (同比例, 倉位置)
_TERM_GUARDS = {"同比": "(?!例)", "倉位": "(?!置)"}
_TERM_PATTERNS = tuple(
    (re.compile(re.escape(src) + _TERM_GUARDS.get(src, "")), dst) for src, dst in TW_INVESTING_TERMS
)


def to_traditional_chinese(content: str) -> str:
    """Convert Simplified Chinese to Taiwan Traditional when REPORT_TRADITIONAL_CHINESE=true."""
    if not content or not env_flag("REPORT_TRADITIONAL_CHINESE"):
        return content
    global _OPENCC_CONVERTER
    try:
        if _OPENCC_CONVERTER is None:
            from opencc import OpenCC

            # s2twp: Simplified -> Traditional (Taiwan) with Taiwan phrasing
            _OPENCC_CONVERTER = OpenCC("s2twp")
        converted = _OPENCC_CONVERTER.convert(content)
        for pattern, tw_term in _TERM_PATTERNS:
            converted = pattern.sub(tw_term, converted)
        return converted
    except Exception as e:  # never block sending because of conversion
        logger.warning("Traditional Chinese conversion failed, sending original text: %s", e)
        return content
