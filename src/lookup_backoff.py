# -*- coding: utf-8 -*-
# Usage: from src.lookup_backoff import failed_recently, mark_failed
# Description: Short negative cache for network lookups used by the compact report
#              (earnings, FinMind chips, TWSE market flows). Successes are cached per
#              day elsewhere; a failure is remembered for a few minutes so repeated
#              report builds in one run do not re-wait on timeouts, while a
#              long-running process still retries later.
# Input: Any hashable key
# Output: bool (failed_recently)
# Dependencies: none (standard library only)
"""Short-lived memory of failed lookups."""

import time
from typing import Dict, Hashable

FAILURE_TTL_SECONDS = 600
_failures: Dict[Hashable, float] = {}


def failed_recently(key: Hashable) -> bool:
    started = _failures.get(key)
    return started is not None and time.monotonic() - started < FAILURE_TTL_SECONDS


def mark_failed(key: Hashable) -> None:
    _failures[key] = time.monotonic()


def clear() -> None:
    """For tests."""
    _failures.clear()
