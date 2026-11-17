# -*- coding: utf-8 -*-
# Usage: from src.env_flags import env_flag; env_flag("REPORT_COMPACT")
# Description: Shared on/off parsing for the report switches added in this fork
#              (REPORT_COMPACT, TELEGRAM_PLAIN_TEXT, REPORT_TRADITIONAL_CHINESE)
# Input: Environment variable name
# Output: True when the value is 1 / true / yes (case-insensitive), else False
# Dependencies: none (standard library only)
"""Shared boolean env-var parsing."""

import os

_TRUE_VALUES = ("1", "true", "yes")


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE_VALUES
