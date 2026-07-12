"""Dreaming tunable defaults mirrored from ``sevn.config.defaults`` (`specs/31-memory-dreaming.md` §10.3).

Module: sevn.memory.dreaming.defaults
Depends: typing.Final

Exports:
    DREAMING_CRON_JOB_ID — stable ``trigger_cron_jobs`` primary key.
    Weight / cap finals — short rationale comments for operators.

Examples:
    >>> "_" in DREAMING_CRON_JOB_ID
    True
"""

from __future__ import annotations

from typing import Final

# Bounded nightly window keeps Dreaming off hot paths; operators override via ``memory.dreaming.cron``.
DEFAULT_DREAMING_THRESHOLD: Final[float] = 0.5
# Recall dominates so repeated facts surface; diversity avoids echo chambers; recency avoids stale noise.
DEFAULT_RECALL_WEIGHT: Final[float] = 0.5
DEFAULT_DIVERSITY_WEIGHT: Final[float] = 0.3
DEFAULT_RECENCY_WEIGHT: Final[float] = 0.2
# Hard cap prevents MEMORY.md spam if the scorer fires on a noisy day.
DEFAULT_MAX_PROMOTIONS_PER_RUN: Final[int] = 8
DEFAULT_BACKFILL_DAYS: Final[int] = 90

DREAMING_CRON_JOB_ID: Final[str] = "sevn_memory_dreaming"
