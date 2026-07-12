"""Voice channel floor regression (`specs/33-self-improvement.md` §11)."""

from __future__ import annotations

from sevn.self_improve.sampler import ShortlistCandidate, allocate_shortlist


def test_voice_channel_floor_reserves_slots() -> None:
    voice = [
        ShortlistCandidate(
            turn_id=f"v{i}",
            bucket="control_random_sample",
            channel="voice",
            intent="chit_chat",
            complexity_tier="A",
        )
        for i in range(3)
    ]
    web = [
        ShortlistCandidate(
            turn_id=f"w{i}",
            bucket="control_random_sample",
            channel="web",
            intent="chit_chat",
            complexity_tier="A",
        )
        for i in range(20)
    ]
    picked, _ = allocate_shortlist(
        candidates=voice + web,
        max_candidates=20,
        explicit_feedback_floor_pct=0.0,
        per_channel_pct_max=0.9,
        per_intent_pct_max=0.9,
        per_tier_pct_max=0.9,
        per_channel_pct_min={"voice": 0.1},
    )
    voice_hits = [c for c in picked if c.channel == "voice"]
    assert len(voice_hits) >= 2
