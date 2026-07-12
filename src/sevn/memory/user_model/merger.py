"""Merge + cap rules for inferred facts (`specs/32-memory-honcho.md` §3.3).

Module: sevn.memory.user_model.merger
Depends: uuid, datetime, sevn.memory.user_model.deny_topics, sevn.memory.user_model.models

Exports:
    UserModelMerger — deterministic merge + prune implementation.

Examples:
    >>> from sevn.memory.user_model.merger import UserModelMerger
    >>> callable(UserModelMerger().merge)
    True
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sevn.memory.user_model.deny_topics import topic_denied
from sevn.memory.user_model.models import InferredFact, UserProfile


def _active_facts(facts: list[InferredFact]) -> list[InferredFact]:
    """Return facts that are still active (not superseded).

    Args:
        facts (list[InferredFact]): Full fact list including inactive rows.

    Returns:
        list[InferredFact]: Only rows with ``superseded_by_id is None``.

    Examples:
        >>> from datetime import UTC, datetime
        >>> from sevn.memory.user_model.models import InferredFact
        >>> from sevn.memory.user_model.merger import _active_facts
        >>> t = datetime(2026, 1, 1, tzinfo=UTC)
        >>> rows = [
        ...     InferredFact(id="a", topic="t", value="1", confidence="high", last_observed_at=t),
        ...     InferredFact(
        ...         id="b",
        ...         topic="t",
        ...         value="2",
        ...         confidence="high",
        ...         last_observed_at=t,
        ...         superseded_by_id="c",
        ...     ),
        ... ]
        >>> [f.id for f in _active_facts(rows)]
        ['a']
    """

    return [f for f in facts if f.superseded_by_id is None]


def _prune_to_max_facts(facts: list[InferredFact], max_facts: int) -> list[InferredFact]:
    """Enforce ``max_facts`` with superseded-first eviction (`specs/32-memory-honcho.md` §3.1).

    Args:
        facts (list[InferredFact]): Working set.
        max_facts (int): Hard cap on stored rows.

    Returns:
        list[InferredFact]: Possibly shortened list respecting invariants.

    Examples:
        >>> from datetime import UTC, datetime
        >>> from sevn.memory.user_model.models import InferredFact
        >>> t = datetime(2026, 1, 1, tzinfo=UTC)
        >>> rows = [
        ...     InferredFact(
        ...         id="a",
        ...         topic="t",
        ...         value="1",
        ...         confidence="high",
        ...         last_observed_at=t,
        ...         superseded_by_id="b",
        ...     ),
        ...     InferredFact(id="b", topic="t", value="2", confidence="high", last_observed_at=t),
        ... ]
        >>> len(_prune_to_max_facts(rows, 1))
        1
    """

    work = list(facts)
    if len(work) <= max_facts:
        return work
    superseded = [f for f in work if f.superseded_by_id is not None]
    superseded.sort(key=lambda f: f.last_observed_at)
    for victim in superseded:
        if len(work) <= max_facts:
            break
        work = [f for f in work if f.id != victim.id]
    while len(work) > max_facts:
        active = [f for f in work if f.superseded_by_id is None]
        if not active:
            break
        active.sort(key=lambda f: f.last_observed_at)
        victim = active[0]
        peers = [f for f in work if f.topic == victim.topic and f.superseded_by_id is None]
        if len(peers) <= 1:
            multi = [
                f
                for f in active
                if sum(1 for g in work if g.topic == f.topic and g.superseded_by_id is None) > 1
            ]
            if not multi:
                break
            multi.sort(key=lambda f: f.last_observed_at)
            victim = multi[0]
        work = [f for f in work if f.id != victim.id]
    return work


class UserModelMerger:
    """Apply §3.3 merge rules; enforce ``max_facts`` prune order."""

    def merge(
        self,
        existing: UserProfile,
        deltas: list[InferredFact],
        *,
        deny_topic_patterns: list[str],
        max_facts: int,
    ) -> UserProfile:
        """Return a new profile with deltas merged and capped.

        Args:
            existing (UserProfile): Current persisted snapshot.
            deltas (list[InferredFact]): New candidate rows from the extractor.
            deny_topic_patterns (list[str]): Literal substring patterns.
            max_facts (int): Maximum rows after merge.

        Returns:
            UserProfile: Updated profile (facts replaced; ``updated_at`` bumped).

        Examples:
            >>> from datetime import UTC, datetime
            >>> from sevn.memory.user_model.merger import UserModelMerger
            >>> from sevn.memory.user_model.models import InferredFact, UserProfile
            >>> base = UserProfile(workspace_id="w", updated_at=datetime(2026, 1, 1, tzinfo=UTC), facts=[])
            >>> d = InferredFact(
            ...     id="1",
            ...     topic="t",
            ...     value="v",
            ...     confidence="high",
            ...     last_observed_at=datetime(2026, 1, 2, tzinfo=UTC),
            ... )
            >>> out = UserModelMerger().merge(base, [d], deny_topic_patterns=[], max_facts=64)
            >>> len(out.facts)
            1
        """

        now = datetime.now(tz=UTC)
        facts: list[InferredFact] = list(existing.facts)
        for d in deltas:
            if topic_denied(d.topic, deny_topic_patterns):
                continue
            d_norm = d.model_copy(
                update={
                    "last_observed_at": d.last_observed_at.astimezone(UTC)
                    if d.last_observed_at.tzinfo
                    else d.last_observed_at.replace(tzinfo=UTC),
                },
            )
            active = _active_facts(facts)
            same_topic = [f for f in active if f.topic == d_norm.topic]
            if not same_topic:
                new_id = d_norm.id or uuid.uuid4().hex[:16]
                facts.append(
                    d_norm.model_copy(
                        update={
                            "id": new_id,
                            "source_session_ids": list(dict.fromkeys(d_norm.source_session_ids))[
                                :5
                            ],
                        },
                    ),
                )
                facts = _prune_to_max_facts(facts, max_facts)
                continue
            exact = next((f for f in same_topic if f.value.strip() == d_norm.value.strip()), None)
            if exact is not None:
                merged_ids = list(
                    dict.fromkeys([*exact.source_session_ids, *d_norm.source_session_ids])
                )[:5]
                lo = exact.last_observed_at.astimezone(UTC)
                ro = d_norm.last_observed_at.astimezone(UTC)
                newer_ts = exact.last_observed_at if lo >= ro else d_norm.last_observed_at
                repl = exact.model_copy(
                    update={
                        "last_observed_at": newer_ts,
                        "source_session_ids": merged_ids,
                    },
                )
                facts = [repl if f.id == exact.id else f for f in facts]
                continue
            new_id = d_norm.id or uuid.uuid4().hex[:16]
            facts = [
                f.model_copy(update={"superseded_by_id": new_id})
                if f.topic == d_norm.topic and f.superseded_by_id is None
                else f
                for f in facts
            ]
            facts.append(
                d_norm.model_copy(
                    update={
                        "id": new_id,
                        "superseded_by_id": None,
                        "source_session_ids": list(dict.fromkeys(d_norm.source_session_ids))[:5],
                    },
                ),
            )
            facts = _prune_to_max_facts(facts, max_facts)

        facts = _prune_to_max_facts(facts, max_facts)
        return existing.model_copy(update={"facts": facts, "updated_at": now})


__all__ = ["UserModelMerger"]
