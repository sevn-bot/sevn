"""Literal-substring deny_topics (`specs/32-memory-honcho.md` §11)."""

from __future__ import annotations

from datetime import UTC, datetime

from sevn.memory.user_model.deny_topics import topic_denied
from sevn.memory.user_model.merger import UserModelMerger
from sevn.memory.user_model.models import InferredFact, UserProfile


def test_topic_denied_literal_substring() -> None:
    assert topic_denied("secret_topic", ["secret"])
    assert not topic_denied("public", ["secret"])


def test_glob_pattern_does_not_match() -> None:
    assert not topic_denied("language", ["*lang"])


def test_merger_drops_denied_delta() -> None:
    base = UserProfile(workspace_id="w", updated_at=datetime(2026, 1, 1, tzinfo=UTC), facts=[])
    d = InferredFact(
        id="n1",
        topic="secret_topic",
        value="x",
        confidence="high",
        last_observed_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    out = UserModelMerger().merge(base, [d], deny_topic_patterns=["secret"], max_facts=64)
    assert out.facts == []
