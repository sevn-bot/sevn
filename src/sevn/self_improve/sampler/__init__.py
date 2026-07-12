"""Deterministic shortlist allocator (`specs/33-self-improvement.md` §3.2).

Module: sevn.self_improve.sampler
Depends: dataclasses, math

Exports:
    ShortlistCandidate — row entering allocator buckets.
    allocate_shortlist — rule-based selection + quota diagnostics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ShortlistCandidate:
    """Sampler-visible trajectory slice."""

    turn_id: str
    bucket: Literal[
        "explicit_feedback",
        "heuristic_regressions",
        "execution_failures",
        "control_random_sample",
    ]
    channel: str
    intent: str | None
    complexity_tier: str | None
    score: float = 0.0
    signals: dict[str, Any] | None = None


def _reserve_channel_floors(
    *,
    picked: list[ShortlistCandidate],
    pool: list[ShortlistCandidate],
    max_candidates: int,
    per_channel_pct_min: dict[str, float],
    ch_counts: dict[str, int],
    intent_counts: dict[str, int],
    tier_counts: dict[str, int],
    intent_cap: int,
    tier_cap: int,
) -> tuple[list[ShortlistCandidate], list[ShortlistCandidate]]:
    """Reserve minimum channel slots before max-cap filling continues.

    Args:
        picked (list[ShortlistCandidate]): Candidates already selected.
        pool (list[ShortlistCandidate]): Remaining ranked pool.
        max_candidates (int): Shortlist size cap.
        per_channel_pct_min (dict[str, float]): Minimum share per channel key.
        ch_counts (dict[str, int]): Mutable per-channel counts for ``picked``.
        intent_counts (dict[str, int]): Mutable per-intent counts.
        tier_counts (dict[str, int]): Mutable per-tier counts.
        intent_cap (int): Max rows per intent bucket.
        tier_cap (int): Max rows per tier bucket.

    Returns:
        tuple[list[ShortlistCandidate], list[ShortlistCandidate]]: Updated ``picked`` and
        ``pool`` after floor reservations.

    Examples:
        >>> from sevn.self_improve.sampler import ShortlistCandidate, _reserve_channel_floors
        >>> picked, pool = _reserve_channel_floors(
        ...     picked=[],
        ...     pool=[],
        ...     max_candidates=4,
        ...     per_channel_pct_min={"voice": 0.25},
        ...     ch_counts={},
        ...     intent_counts={},
        ...     tier_counts={},
        ...     intent_cap=4,
        ...     tier_cap=4,
        ... )
        >>> picked == [] and pool == []
        True
    """
    if not per_channel_pct_min or max_candidates <= len(picked):
        return picked, pool

    picked_ids = {c.turn_id for c in picked}
    remaining_pool = [c for c in pool if c.turn_id not in picked_ids]
    for channel, pct_min in sorted(per_channel_pct_min.items()):
        if pct_min <= 0.0:
            continue
        need = min(max_candidates - len(picked), math.ceil(pct_min * max_candidates))
        have = ch_counts.get(channel, 0)
        if have >= need:
            continue
        channel_rows = sorted(
            (c for c in remaining_pool if c.channel == channel),
            key=lambda c: c.turn_id,
        )
        for cand in channel_rows:
            if len(picked) >= max_candidates or ch_counts.get(channel, 0) >= need:
                break
            ik = cand.intent or ""
            tk = cand.complexity_tier or ""
            if intent_counts.get(ik, 0) >= intent_cap:
                continue
            if tier_counts.get(tk, 0) >= tier_cap:
                continue
            picked.append(cand)
            picked_ids.add(cand.turn_id)
            ch_counts[cand.channel] = ch_counts.get(cand.channel, 0) + 1
            intent_counts[ik] = intent_counts.get(ik, 0) + 1
            tier_counts[tk] = tier_counts.get(tk, 0) + 1

    remaining_pool = [c for c in pool if c.turn_id not in picked_ids]
    return picked, remaining_pool


def allocate_shortlist(
    *,
    candidates: list[ShortlistCandidate],
    max_candidates: int,
    explicit_feedback_floor_pct: float,
    per_channel_pct_max: float,
    per_intent_pct_max: float,
    per_tier_pct_max: float,
    per_channel_pct_min: dict[str, float] | None = None,
) -> tuple[list[ShortlistCandidate], list[str]]:
    """Pick up to ``max_candidates`` rows with explicit-feedback reservation.

    Args:
    candidates (list[ShortlistCandidate]): Pool after noise filtering.
    max_candidates (int): Hard cap for this job run.
    explicit_feedback_floor_pct (float): Minimum fraction reserved for explicit bucket.
    per_channel_pct_max (float): Max fraction sharing one channel label.
    per_intent_pct_max (float): Max fraction sharing one intent label (``\"\"`` buckets separately).
    per_tier_pct_max (float): Max fraction sharing one tier label.
    per_channel_pct_min (dict[str, float] | None): Minimum fraction per channel key (e.g. ``voice``).

    Returns:
        tuple[list[ShortlistCandidate], list[str]]: Selected rows + diagnostic warnings.

    Examples:
        >>> allocate_shortlist(
        ...     candidates=[
        ...         ShortlistCandidate(
        ...             turn_id="e1",
        ...             bucket="explicit_feedback",
        ...             channel="web",
        ...             intent=None,
        ...             complexity_tier=None,
        ...         ),
        ...         ShortlistCandidate(
        ...             turn_id="c1",
        ...             bucket="control_random_sample",
        ...             channel="telegram",
        ...             intent=None,
        ...             complexity_tier=None,
        ...         ),
        ...     ],
        ...     max_candidates=10,
        ...     explicit_feedback_floor_pct=0.2,
        ...     per_channel_pct_max=0.5,
        ...     per_intent_pct_max=0.5,
        ...     per_tier_pct_max=0.5,
        ... )[0][0].turn_id
        'e1'
    """
    diagnostics: list[str] = []
    if max_candidates <= 0:
        return [], diagnostics

    explicit_pool = [c for c in candidates if c.bucket == "explicit_feedback"]
    other_pool = [c for c in candidates if c.bucket != "explicit_feedback"]

    reserved = 0
    if explicit_pool and explicit_feedback_floor_pct > 0.0:
        reserved = min(max_candidates, math.ceil(max_candidates * explicit_feedback_floor_pct))
        need = len(explicit_pool)
        if reserved < need:
            diagnostics.append(
                f"sampler_quota_conflict: explicit_feedback wants {need} slots "
                f"but only {reserved} reserved by floor_pct",
            )

    picked: list[ShortlistCandidate] = []
    explicit_sorted = sorted(explicit_pool, key=lambda c: c.turn_id)
    cap_explicit = min(reserved, len(explicit_sorted), max_candidates)
    picked.extend(explicit_sorted[:cap_explicit])

    channel_cap = max(1, math.ceil(per_channel_pct_max * max_candidates))
    intent_cap = max(1, math.ceil(per_intent_pct_max * max_candidates))
    tier_cap = max(1, math.ceil(per_tier_pct_max * max_candidates))

    ch_counts: dict[str, int] = {}
    intent_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}

    def _bump_counts(c: ShortlistCandidate) -> None:
        ch_counts[c.channel] = ch_counts.get(c.channel, 0) + 1
        ik = c.intent or ""
        intent_counts[ik] = intent_counts.get(ik, 0) + 1
        tk = c.complexity_tier or ""
        tier_counts[tk] = tier_counts.get(tk, 0) + 1

    for c in picked:
        _bump_counts(c)

    floor_mins = per_channel_pct_min or {}
    picked, other_pool = _reserve_channel_floors(
        picked=picked,
        pool=other_pool,
        max_candidates=max_candidates,
        per_channel_pct_min=floor_mins,
        ch_counts=ch_counts,
        intent_counts=intent_counts,
        tier_counts=tier_counts,
        intent_cap=intent_cap,
        tier_cap=tier_cap,
    )

    remaining = max_candidates - len(picked)
    if remaining <= 0:
        return picked, diagnostics

    for cand in sorted(other_pool, key=lambda c: c.turn_id):
        if remaining <= 0:
            break
        ik = cand.intent or ""
        tk = cand.complexity_tier or ""
        if ch_counts.get(cand.channel, 0) >= channel_cap:
            continue
        if intent_counts.get(ik, 0) >= intent_cap:
            continue
        if tier_counts.get(tk, 0) >= tier_cap:
            continue
        picked.append(cand)
        _bump_counts(cand)
        remaining -= 1

    if len(picked) < max_candidates and other_pool:
        diagnostics.append("sampler_coverage_shortfall: caps prevented filling max_candidates")

    return picked, diagnostics
