"""Sampler floor regression for explicit feedback (`specs/33-self-improvement.md` §9)."""

from __future__ import annotations

from sevn.self_improve.sampler import ShortlistCandidate, allocate_shortlist


def test_explicit_feedback_survives_large_benign_pool() -> None:
    explicit = [
        ShortlistCandidate(
            turn_id=f"e{i}",
            bucket="explicit_feedback",
            channel="web",
            intent="support",
            complexity_tier="B",
        )
        for i in range(5)
    ]
    benign = [
        ShortlistCandidate(
            turn_id=f"c{i}",
            bucket="control_random_sample",
            channel="telegram",
            intent="chit_chat",
            complexity_tier="A",
        )
        for i in range(10_000)
    ]
    picked, _ = allocate_shortlist(
        candidates=explicit + benign,
        max_candidates=100,
        explicit_feedback_floor_pct=0.2,
        per_channel_pct_max=0.6,
        per_intent_pct_max=0.6,
        per_tier_pct_max=0.6,
    )
    explicit_hits = {c.turn_id for c in picked if c.bucket == "explicit_feedback"}
    assert explicit_hits == {f"e{i}" for i in range(5)}
