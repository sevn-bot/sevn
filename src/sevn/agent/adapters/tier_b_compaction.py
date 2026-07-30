"""Tier-B history compaction — harness compaction menu factory (D9/W6).

Opt-in tier-B conversation compaction via pydantic-ai-harness strategies. Default-off
so existing capability inventory and history behavior stay unchanged until explicitly
enabled.

Module: sevn.agent.adapters.tier_b_compaction
Depends: pydantic_ai_harness.compaction, sevn.config.defaults

Exports:
    build_compaction_capability — factory returning one harness compaction capability.
    compact_history_if_enabled — test/helper seam for standalone history compaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.tools import RunContext
from pydantic_ai_harness.compaction import (
    ClampOversizedMessages,
    ClearToolResults,
    SummarizingCompaction,
    TieredCompaction,
)

from sevn.config.defaults import (
    DEFAULT_TIER_B_HISTORY_COMPACTION_STRATEGY,
    DEFAULT_TIER_B_HISTORY_COMPACTION_TARGET_TOKENS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic_ai.capabilities.abstract import AbstractCapability
    from pydantic_ai.models import Model

TierBHistoryCompactionStrategy = Literal[
    "tiered",
    "summarizing",
    "clear_tool_results",
    "clamp_oversized",
]

_CLAMP_MAX_PART_CHARS: int = 50_000
_CLAMP_KEEP_HEAD_CHARS: int = 2_000
_CLAMP_KEEP_TAIL_CHARS: int = 2_000
_CLEAR_MAX_TOKENS: int = 100_000
_CLEAR_KEEP_PAIRS: int = 5
_SUMMARIZE_MAX_MESSAGES: int = 60
_SUMMARIZE_KEEP_MESSAGES: int = 20


def build_compaction_capability(
    *,
    strategy: TierBHistoryCompactionStrategy = DEFAULT_TIER_B_HISTORY_COMPACTION_STRATEGY,
    target_tokens: int = DEFAULT_TIER_B_HISTORY_COMPACTION_TARGET_TOKENS,
    summary_model: str | Model | None = None,
) -> AbstractCapability[Any]:
    """Build one harness history-compaction capability for tier-B (D9).

    Args:
        strategy (TierBHistoryCompactionStrategy): Compaction menu entry to wire.
        target_tokens (int): Token budget for ``TieredCompaction`` escalation stop.
        summary_model (str | Model | None): Optional summarizer model; ``None`` inherits
            the running agent's model at compaction time.

    Returns:
        AbstractCapability: Configured compaction capability for ``Agent(capabilities=...)``.

    Examples:
        >>> cap = build_compaction_capability(strategy="clamp_oversized")
        >>> cap.__class__.__name__
        'ClampOversizedMessages'
    """
    if strategy == "clamp_oversized":
        return ClampOversizedMessages(
            max_part_chars=_CLAMP_MAX_PART_CHARS,
            keep_head_chars=_CLAMP_KEEP_HEAD_CHARS,
            keep_tail_chars=_CLAMP_KEEP_TAIL_CHARS,
        )
    if strategy == "clear_tool_results":
        return ClearToolResults(
            max_tokens=_CLEAR_MAX_TOKENS,
            keep_pairs=_CLEAR_KEEP_PAIRS,
        )
    if strategy == "summarizing":
        return SummarizingCompaction(
            model=summary_model,
            max_messages=_SUMMARIZE_MAX_MESSAGES,
            keep_messages=_SUMMARIZE_KEEP_MESSAGES,
        )
    return TieredCompaction(
        tiers=[
            ClampOversizedMessages(
                max_part_chars=_CLAMP_MAX_PART_CHARS,
                keep_head_chars=_CLAMP_KEEP_HEAD_CHARS,
                keep_tail_chars=_CLAMP_KEEP_TAIL_CHARS,
            ),
            ClearToolResults(
                max_tokens=_CLEAR_MAX_TOKENS,
                keep_pairs=_CLEAR_KEEP_PAIRS,
            ),
            SummarizingCompaction(
                model=summary_model,
                max_messages=_SUMMARIZE_MAX_MESSAGES,
                keep_messages=_SUMMARIZE_KEEP_MESSAGES,
            ),
        ],
        target_tokens=target_tokens,
    )


async def compact_history_if_enabled(
    messages: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = False,
    strategy: TierBHistoryCompactionStrategy = DEFAULT_TIER_B_HISTORY_COMPACTION_STRATEGY,
    target_tokens: int = DEFAULT_TIER_B_HISTORY_COMPACTION_TARGET_TOKENS,
) -> list[dict[str, Any]]:
    """Compact plain message dicts when the tier-B compaction toggle is on (W1.7 seam).

    Args:
        messages (Sequence[Mapping[str, Any]]): History rows as ``{"role", "content"}`` dicts.
        enabled (bool): When ``False``, return the input unchanged.
        strategy (TierBHistoryCompactionStrategy): Compaction menu entry to apply.
        target_tokens (int): Token budget for ``TieredCompaction`` escalation stop.

    Returns:
        list[dict[str, Any]]: Possibly compacted history in the same dict shape.

    Examples:
        >>> import asyncio
        >>> rows = [{"role": "user", "content": "hello"}]
        >>> asyncio.run(compact_history_if_enabled(rows, enabled=False)) == rows
        True
    """
    rows = [dict(message) for message in messages]
    if not enabled or not rows:
        return rows

    model_messages: list[ModelMessage] = []
    for message in rows:
        if str(message.get("role", "user")) == "user":
            model_messages.append(
                ModelRequest(parts=[UserPromptPart(content=str(message.get("content", "")))]),
            )
    if not model_messages:
        return rows

    capability = build_compaction_capability(strategy=strategy, target_tokens=target_tokens)
    compact = getattr(capability, "compact", None)
    if compact is None:
        return rows

    from pydantic_ai.models.test import TestModel
    from pydantic_ai.usage import RunUsage

    class _CompactionDeps:
        """Minimal deps bag for standalone compaction calls."""

    ctx = RunContext(deps=_CompactionDeps(), model=TestModel(), usage=RunUsage())
    compacted = await compact(model_messages, ctx)
    out_rows: list[dict[str, Any]] = []
    for message in compacted:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                out_rows.append({"role": "user", "content": part.content})
    return out_rows


__all__ = [
    "TierBHistoryCompactionStrategy",
    "build_compaction_capability",
    "compact_history_if_enabled",
]
