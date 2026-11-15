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
        return _OPENCC_CONVERTER.convert(content)
    except Exception as e:  # never block sending because of conversion
        logger.warning("Traditional Chinese conversion failed, sending original text: %s", e)
        return content
