"""Status freshness: is the status line recent enough to score at all?

Deterministic rules, no scoring:

  1. The record that carried the status has its own timestamp
       -> age is known. STALE if age > limit, else FRESH.
  2. No record timestamp, but the transcript file's mtime is older than
     the limit -> the status is at least that old. STALE.
  3. Otherwise -> UNVERIFIED. The status is still scored, and the audit
     record says its age could not be established.

A file's mtime can prove a status is old but never that it is fresh: a
transcript that is still being written to may contain a status line from
hours ago.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .polling.base import StatusReading

FRESH = "FRESH"
STALE = "STALE"
UNVERIFIED = "UNVERIFIED"

# The WARDEN_RULE asks for one status every 10 minutes; the default limit
# is three missed emissions.
DEFAULT_STALE_AFTER_SECONDS = 1800


@dataclass(frozen=True)
class Freshness:
    state: str                         # FRESH | STALE | UNVERIFIED
    age_seconds: Optional[float]       # known age (rule 1), else None
    min_age_seconds: Optional[float]   # lower bound on age (rule 2/3), else None
    basis: str                         # which evidence decided it


def assess(
    reading: Optional[StatusReading],
    now: datetime,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> Freshness:
    if reading is None:
        return Freshness(UNVERIFIED, None, None, "no-status")

    if reading.observed_at is not None:
        # A timestamp ahead of our clock is clock skew, not a negative age.
        age = max(0.0, (now - reading.observed_at).total_seconds())
        state = STALE if age > stale_after_seconds else FRESH
        return Freshness(state, age, None, reading.time_source)

    if reading.latest_possible_at is not None:
        min_age = max(0.0, (now - reading.latest_possible_at).total_seconds())
        if min_age > stale_after_seconds:
            return Freshness(STALE, None, min_age, reading.time_source)
        return Freshness(UNVERIFIED, None, min_age, reading.time_source)

    return Freshness(UNVERIFIED, None, None, reading.time_source)


def format_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"
