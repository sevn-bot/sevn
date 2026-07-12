"""Deterministic lexical recall without LLM ranking (`specs/33-self-improvement.md` §4.5).

Module: sevn.self_improve.lessons
Depends: dataclasses, re, typing

Exports:
    Lesson — minimal lesson payload.
    recall_lessons — token Jaccard ordering (no embeddings).
    emit_recall_audit — best-effort trace span helper for recalls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class Lesson:
    """Graduated lesson row used for deterministic recall."""

    lesson_id: str
    text: str
    intents: frozenset[str]


def _tokens(text: str) -> set[str]:
    """Normalize text into alphanumeric tokens shared by recall helpers.

    Args:
        text (str): Arbitrary inbound Unicode string.

    Returns:
        set[str]: Lowercased tokens after splitting punctuation and whitespace.

    Examples:
        >>> sorted(_tokens("a-b")) == ["a", "b"]
        True
    """
    parts = re.split(r"[^a-z0-9]+", text.lower())
    return {p for p in parts if p}


def recall_lessons(intent: str, *, lessons: list[Lesson], limit: int = 5) -> list[Lesson]:
    """Rank corpus lessons by token-set overlap against ``intent``.

    Args:
        intent (str): Routing intent label from ontology hygiene.
        lessons (list[Lesson]): Corpus loaded by caller (usually JSONL readers).
        limit (int): Maximum hits.

    Returns:
        list[Lesson]: Stable ordering by descending score then ``lesson_id``.

    Examples:
        >>> recall_lessons(
        ...     "plan todos",
        ...     lessons=[
        ...         Lesson("a", "capture todos daily", frozenset({"plan"})),
        ...         Lesson("b", "unrelated", frozenset()),
        ...     ],
        ...     limit=1,
        ... )[0].lesson_id
        'a'
    """
    seed = _tokens(intent)
    scored: list[tuple[float, str, Lesson]] = []
    for les in lessons:
        les_tokens = _tokens(les.text)
        les_tokens |= {t.lower() for t in les.intents}
        overlap = len(seed & les_tokens)
        union = len(seed | les_tokens) or 1
        scored.append((overlap / union, les.lesson_id, les))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


async def emit_recall_audit(
    trace: object,
    *,
    session_id: str,
    turn_id: str,
    hits: list[str],
) -> None:
    """Emit episodic recall diagnostics when sinks support spans.

    Args:
    trace (object): Active tracing sink for the session (duck-typed ``emit``).
    session_id (str): Gateway session identifier.
    turn_id (str): Stable trajectory key.
    hits (list[str]): Lesson ids surfaced to suffix injection.

    Returns:
        None: Best-effort no-op when sinks omit bespoke hooks.

    Examples:
        >>> import asyncio
        >>> from unittest.mock import MagicMock
        >>> trace = MagicMock()
        >>> asyncio.run(
        ...     emit_recall_audit(trace, session_id="s", turn_id="t", hits=["l1"]),
        ... ) is None
        True
    """
    emit = getattr(trace, "emit", None)
    if callable(emit):
        maybe = emit(
            "self_improve.lessons.recall",
            {"session_id": session_id, "turn_id": turn_id, "hits": hits},
        )
        if hasattr(maybe, "__await__"):
            await cast("Any", maybe)
    return
