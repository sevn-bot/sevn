"""Render Triager-facing profile bullets (`specs/32-memory-honcho.md` §2.5).

Module: sevn.memory.user_model.renderer
Depends: datetime, sevn.memory.user_model.models

Exports:
    render_profile_block — Markdown-ish lines for personality breakpoint injection.

Examples:
    >>> from sevn.memory.user_model.renderer import render_profile_block
    >>> render_profile_block(None, max_tokens=100, now=__import__("datetime").datetime.now())
    ''
"""

from __future__ import annotations

from datetime import datetime

from sevn.memory.user_model.models import UserProfile

_CONF_ORDER = {"high": 0, "medium": 1, "low": 2}


def _approx_tokens(text: str) -> int:
    """Very rough token estimate for ``max_tokens`` ceiling.

    Args:
        text (str): Candidate render text.

    Returns:
        int: Estimated token count (minimum 1 when non-empty).

    Examples:
        >>> _approx_tokens("abcd")
        1
    """

    if not text:
        return 0
    return max(1, len(text) // 4)


def render_profile_block(
    profile: UserProfile | None,
    *,
    max_tokens: int,
    now: datetime,
) -> str:
    """Markdown-ish bullet list; empty when disabled or no active facts.

    Args:
        profile (UserProfile | None): Snapshot to render (``None`` treated as empty).
        max_tokens (int): Rough token budget for emitted text.
        now (datetime): Reserved for future relative dating (callers should pass UTC).

    Returns:
        str: Non-empty markdown-ish block, or empty string when nothing to inject.

    Examples:
        >>> from datetime import UTC, datetime
        >>> from sevn.memory.user_model.models import InferredFact, UserProfile
        >>> now = datetime(2026, 5, 1, tzinfo=UTC)
        >>> prof = UserProfile(
        ...     workspace_id="w",
        ...     updated_at=now,
        ...     facts=[
        ...         InferredFact(
        ...             id="1",
        ...             topic="t",
        ...             value="v",
        ...             confidence="high",
        ...             last_observed_at=now,
        ...         ),
        ...     ],
        ... )
        >>> "- t:" in render_profile_block(prof, max_tokens=200, now=now)
        True
    """

    _ = now
    if profile is None or not profile.facts:
        return ""
    active = [f for f in profile.facts if f.superseded_by_id is None]
    if not active:
        return ""
    active.sort(
        key=lambda f: (
            _CONF_ORDER[f.confidence],
            -f.last_observed_at.timestamp(),
        ),
    )
    lines: list[str] = []
    for f in active:
        seen = f.last_observed_at.date().isoformat()
        line = f"- {f.topic}: {f.value} ({f.confidence}; last seen {seen})"
        candidate = "\n".join([*lines, line]).strip()
        if lines and _approx_tokens(candidate) > max_tokens:
            break
        lines.append(line)
    return "\n".join(lines).strip()


__all__ = ["render_profile_block"]
