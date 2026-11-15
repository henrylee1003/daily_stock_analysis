# -*- coding: utf-8 -*-
"""Optional Simplified -> Taiwan Traditional Chinese conversion for outgoing messages."""

import logging
import os

logger = logging.getLogger(__name__)


_OPENCC_CONVERTER = None


def to_traditional_chinese(content: str) -> str:
    """Convert Simplified Chinese to Taiwan Traditional when REPORT_TRADITIONAL_CHINESE=true."""
    if not content or os.getenv("REPORT_TRADITIONAL_CHINESE", "").strip().lower() not in ("1", "true", "yes"):
        return content
    global _OPENCC_CONVERTER
    try:
        if _OPENCC_CONVERTER is None:
            from opencc import OpenCC

            # s2twp: Simplified -> Traditional (Taiwan) with Taiwan phrasing
            _OPENCC_CONVERTER = OpenCC("s2twp")
        converted = _OPENCC_CONVERTER.convert(content)
        # OpenCC maps 复盘 to 覆盤; Taiwan usage is 復盤
        return converted.replace("覆盤", "復盤")
    except Exception as e:  # never block sending because of conversion
        logger.warning("Traditional Chinese conversion failed, sending original text: %s", e)
        return content
