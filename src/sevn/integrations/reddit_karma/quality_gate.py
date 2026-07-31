"""Quality gate for Reddit karma loop candidates (#74, W33.4).

Module: sevn.integrations.reddit_karma.quality_gate
Depends: dataclasses, typing

Exports:
    RedditCandidate — normalized discovery candidate.
    evaluate_candidate — apply recency/relevance/rules/promo/expertise checks.
    candidate_from_dict — build candidate from discovery JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RedditCandidate:
    """One Reddit thread candidate discovered via browser medium."""

    subreddit: str
    title: str
    url: str
    age_hours: float
    comment_count: int
    has_existing_sevn_comment: bool
    promotional_risk: float
    source_backed: bool
    subreddit_allowed: bool
    topic_match: bool


def evaluate_candidate(candidate: RedditCandidate) -> tuple[bool, str | None]:
    """Return ``(accepted, skip_reason)`` after applying the W33 quality gate.

    Checks: recency, relevance (topic match), subreddit allow-list, existing
    comments, promotional risk, and source-backed expertise.

    Args:
        candidate (RedditCandidate): Normalized candidate metadata.

    Returns:
        tuple[bool, str | None]: ``(True, None)`` when accepted; otherwise skip reason.

    Examples:
        >>> c = RedditCandidate(
        ...     subreddit="python", title="help", url="https://reddit.com/x", age_hours=1,
        ...     comment_count=3, has_existing_sevn_comment=False, promotional_risk=0.1,
        ...     source_backed=True, subreddit_allowed=True, topic_match=True,
        ... )
        >>> evaluate_candidate(c)
        (True, None)
    """
    if not candidate.subreddit_allowed:
        return False, "subreddit not in configured allow-list"
    if candidate.age_hours > 72:
        return False, "thread too old (recency gate)"
    if not candidate.topic_match:
        return False, "topic relevance below threshold"
    if candidate.has_existing_sevn_comment:
        return False, "existing sevn comment on thread"
    if candidate.promotional_risk >= 0.6:
        return False, "promotional risk too high"
    if not candidate.source_backed:
        return False, "no approved wiki/second-brain source backing"
    if candidate.comment_count > 200:
        return False, "thread already saturated with comments"
    return True, None


def candidate_from_dict(
    raw: dict[str, Any], *, allowed_subreddits: frozenset[str]
) -> RedditCandidate:
    """Build :class:`RedditCandidate` from a discovery payload dict.

    Args:
        raw (dict[str, Any]): Discovery row from browser/search results.
        allowed_subreddits (frozenset[str]): Lower-case configured allow-list.

    Returns:
        RedditCandidate: Normalized candidate for gating.

    Examples:
        >>> c = candidate_from_dict({"subreddit": "python", "title": "q"}, allowed_subreddits=frozenset())
        >>> c.subreddit
        'python'
    """
    subreddit = str(raw.get("subreddit") or "").strip().removeprefix("r/")
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "").strip()
    age_hours = float(raw.get("age_hours") or 0.0)
    comment_count = int(raw.get("comment_count") or 0)
    return RedditCandidate(
        subreddit=subreddit,
        title=title,
        url=url,
        age_hours=age_hours,
        comment_count=comment_count,
        has_existing_sevn_comment=bool(raw.get("has_existing_sevn_comment")),
        promotional_risk=float(raw.get("promotional_risk") or 0.0),
        source_backed=bool(raw.get("source_backed")),
        subreddit_allowed=(not allowed_subreddits) or subreddit.lower() in allowed_subreddits,
        topic_match=bool(raw.get("topic_match", True)),
    )


__all__ = ["RedditCandidate", "candidate_from_dict", "evaluate_candidate"]
