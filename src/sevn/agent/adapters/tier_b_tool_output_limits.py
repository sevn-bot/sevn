"""Tier-B tool output limits — harness ``ToolOutputLimits`` factory (D6/D7).

Replaces the hand-rolled ``tier_b_overflow`` shim with pydantic-ai-harness
``ToolOutputLimits``. Results up to ``spill_threshold`` pass through in full (the
operator full-content directive); only pathological oversize payloads spill to disk
with a head+tail preview and ``read_tool_result`` paging.

Module: sevn.agent.adapters.tier_b_tool_output_limits
Depends: pydantic_ai_harness.tool_output_limits

Exports:
    OVERFLOW_TRUNCATE_FLOOR, OVERFLOW_SPILL_THRESHOLD — tier-B overflow thresholds.
    build_overflow_capability — factory returning harness ``ToolOutputLimits``.

Examples:
    >>> cap = build_overflow_capability()
    >>> cap.__class__.__name__
    'ToolOutputLimits'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai_harness.tool_output_limits import Band, LocalFileStore, Spill, ToolOutputLimits

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.capabilities.abstract import AbstractCapability

OVERFLOW_TRUNCATE_FLOOR: int = 4096
"""Retained for back-compat; harness bands no longer truncate below ``spill_threshold``."""

OVERFLOW_SPILL_THRESHOLD: int = 1_048_576
"""Inline ceiling (1 MiB): results below this reach the model in full (D7)."""

_SPILL_HEAD_CHARS: int = 4096
"""Head preview budget for safety-valve spills (matches prior sevn shim)."""

_SPILL_TAIL_CHARS: int = 2048
"""Tail preview budget for safety-valve spills (matches prior sevn shim)."""


def build_overflow_capability(
    *,
    truncate_floor: int = OVERFLOW_TRUNCATE_FLOOR,
    spill_threshold: int = OVERFLOW_SPILL_THRESHOLD,
    spill_dir: Path | None = None,
) -> AbstractCapability[Any]:
    """Build the tier-B overflow capability via harness ``ToolOutputLimits`` (D6).

    Args:
        truncate_floor (int): Retained for API compat; no longer truncates (D7).
        spill_threshold (int): Inline ceiling — only results ≥ this size spill.
        spill_dir (Path | None): Optional ``LocalFileStore`` root for spill files.

    Returns:
        AbstractCapability: Configured ``ToolOutputLimits`` instance.

    Examples:
        >>> cap = build_overflow_capability(truncate_floor=1024, spill_threshold=8192)
        >>> cap.bands[0].over
        8192
    """
    _ = truncate_floor
    kwargs: dict[str, Any] = {
        "bands": [
            Band(
                over=spill_threshold,
                action=Spill(preview_chars=_SPILL_HEAD_CHARS + _SPILL_TAIL_CHARS),
            )
        ],
    }
    if spill_dir is not None:
        kwargs["store"] = LocalFileStore(base_dir=spill_dir)
    return ToolOutputLimits(**kwargs)


__all__ = [
    "OVERFLOW_SPILL_THRESHOLD",
    "OVERFLOW_TRUNCATE_FLOOR",
    "build_overflow_capability",
]
