"""Triager subtree models for ``sevn.json``.

Module: sevn.config.sections.triager
Depends: pydantic, sevn.config.defaults

Exports:
    TriagerTimeoutConfig — ``triager.timeout`` staircase (``specs/13-rlm-triager.md`` §5).
    TriagerWorkspaceConfig — ``triager`` subtree (same).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
    DEFAULT_TRIAGER_TIER_B_SKILL_CAP,
    DEFAULT_TRIAGER_TIER_B_TOOL_CAP,
    DEFAULT_TRIAGER_TIMEOUT_HARD_S,
    DEFAULT_TRIAGER_TIMEOUT_INDICATOR_S,
    DEFAULT_TRIAGER_TIMEOUT_WARN2_S,
    DEFAULT_TRIAGER_TIMEOUT_WARN_S,
)


class TriagerTimeoutConfig(BaseModel):
    """``triager.timeout`` staircase (`specs/13-rlm-triager.md` §5)."""

    model_config = ConfigDict(extra="allow")

    indicator_s: float = Field(default=DEFAULT_TRIAGER_TIMEOUT_INDICATOR_S, ge=0.0)
    warn_s: float = Field(default=DEFAULT_TRIAGER_TIMEOUT_WARN_S, ge=0.0)
    warn2_s: float = Field(default=DEFAULT_TRIAGER_TIMEOUT_WARN2_S, ge=0.0)
    hard_s: float = Field(default=DEFAULT_TRIAGER_TIMEOUT_HARD_S, ge=0.0)


class TriagerWorkspaceConfig(BaseModel):
    """Typed ``triager`` subtree in ``sevn.json`` (`specs/13-rlm-triager.md` §5)."""

    model_config = ConfigDict(extra="allow")

    tier_b_tool_cap: int = Field(default=DEFAULT_TRIAGER_TIER_B_TOOL_CAP, ge=1)
    tier_b_skill_cap: int = Field(default=DEFAULT_TRIAGER_TIER_B_SKILL_CAP, ge=1)
    tier_b_truncation: Literal["tail", "score"] = "tail"
    history_turns_n: int = Field(
        default=40,
        ge=0,
        validation_alias=AliasChoices("history_turns_N", "history_turns_n"),
    )
    timeout: TriagerTimeoutConfig | None = None
    group_scope: Literal["all", "addressed_only"] = "all"
    relax_greeting_lists: bool = False
    on_unknown_named_tool: Literal["strip", "abort"] = "strip"
    disregard_non_a_complexity: Literal["coerce", "abort"] = Field(default="coerce")
    deterministic_seed: int | None = None
    low_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    fast_greeting_path: bool = Field(
        default=True,
        description="Pre-LLM tier-A synthesis for strict greetings (legacy fast_mode).",
    )
    fast_continuation_path: bool = Field(
        default=True,
        description=(
            "Pre-LLM replay of prior routing for short continuations "
            '("so?", "go ahead", "try again") when a tier-B/C/D task is in flight.'
        ),
    )
    cheap_model_id: str | None = Field(
        default=None,
        description=(
            "Optional faster model id for triage on obvious continuations that "
            "miss the replay fast-path; tier-B/C/D executors keep their own slots."
        ),
    )
    complexity_clamp_confidence_threshold: float = Field(
        default=DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
        ge=0.0,
        le=1.0,
        description=(
            "Below this Triager confidence, short/vague C/D routes clamp to tier B "
            "(`specs/13-rlm-triager.md`)."
        ),
    )
    complexity_clamp_short_word_limit: int = Field(
        default=DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
        ge=1,
        description=(
            "Word-count ceiling for the complexity clamp when confidence is low "
            "(`specs/13-rlm-triager.md`)."
        ),
    )
