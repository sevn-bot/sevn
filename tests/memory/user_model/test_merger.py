"""Unit tests for ``UserModelMerger`` (`specs/32-memory-honcho.md` §3.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from sevn.memory.user_model.merger import UserModelMerger
from sevn.memory.user_model.models import InferredFact, UserProfile


def _fact(
    *,
    fid: str,
    topic: str,
    value: str,
    superseded: str | None = None,
    ts: datetime | None = None,
) -> InferredFact:
    return InferredFact(
        id=fid,
        topic=topic,
        value=value,
        confidence="high",
        source_session_ids=["s1"],
        last_observed_at=ts or datetime(2026, 1, 1, tzinfo=UTC),
        superseded_by_id=superseded,
    )


def test_merge_new_topic_appends() -> None:
    base = UserProfile(workspace_id="w", updated_at=datetime(2026, 1, 1, tzinfo=UTC), facts=[])
    merger = UserModelMerger()
    d = _fact(fid="n1", topic="lang", value="Python")
    out = merger.merge(base, [d], deny_topic_patterns=[], max_facts=64)
    assert len(out.facts) == 1
    assert out.facts[0].topic == "lang"


def test_merge_same_value_bumps_timestamp() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    base = UserProfile(
        workspace_id="w",
        updated_at=t0,
        facts=[_fact(fid="a", topic="lang", value="Python", ts=t0)],
    )
    merger = UserModelMerger()
    out = merger.merge(
        base,
        [_fact(fid="x", topic="lang", value="Python", ts=t1)],
        deny_topic_patterns=[],
        max_facts=64,
    )
    assert len(out.facts) == 1
    assert out.facts[0].last_observed_at == t1


def test_merge_contradiction_supersedes() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 2, 1, tzinfo=UTC)
    base = UserProfile(
        workspace_id="w",
        updated_at=t0,
        facts=[_fact(fid="old", topic="lang", value="Python", ts=t0)],
    )
    merger = UserModelMerger()
    delta = _fact(fid="new", topic="lang", value="Go", ts=t1)
    out = merger.merge(base, [delta], deny_topic_patterns=[], max_facts=64)
    active = [f for f in out.facts if f.superseded_by_id is None]
    assert len(active) == 1
    assert active[0].value == "Go"
    old = next(f for f in out.facts if f.id == "old")
    assert old.superseded_by_id == active[0].id


def test_deny_topic_drops_delta() -> None:
    base = UserProfile(workspace_id="w", updated_at=datetime(2026, 1, 1, tzinfo=UTC), facts=[])
    merger = UserModelMerger()
    d = _fact(fid="n1", topic="secret_topic", value="x")
    out = merger.merge(base, [d], deny_topic_patterns=["secret"], max_facts=64)
    assert out.facts == []


def test_max_facts_prunes_superseded_first() -> None:
    t = datetime(2026, 1, 1, tzinfo=UTC)
    facts = [
        _fact(fid="a", topic="t1", value="1", superseded="b", ts=t),
        _fact(fid="b", topic="t1", value="2", ts=t),
    ]
    base = UserProfile(workspace_id="w", updated_at=t, facts=facts)
    merger = UserModelMerger()
    out = merger.merge(base, [], deny_topic_patterns=[], max_facts=1)
    assert len(out.facts) <= 1
