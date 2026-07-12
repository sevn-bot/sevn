"""Memory and LCM subtree models for ``sevn.json``.

Module: sevn.config.sections.memory
Depends: pydantic, sevn.config.defaults

Exports:
    MemoryPreCompactionFlushWorkspaceConfig — ``memory.pre_compaction_flush`` (`specs/15-memory-lcm.md` §5).
    DreamingLlmRankerWorkspaceConfig — ``memory.dreaming.scoring.llm_ranker`` (`specs/31-memory-dreaming.md` §5).
    DreamingScoringWorkspaceConfig — ``memory.dreaming.scoring`` (same).
    DreamingWorkspaceConfig — ``memory.dreaming`` toggle + schedule (`specs/31-memory-dreaming.md` §5).
    UserModelWorkspaceConfig — ``memory.user_model`` (`specs/32-memory-honcho.md` §3.2).
    MemoryWorkspaceSectionConfig — typed ``memory`` subtree.
    LcmWorkspaceConfig — ``lcm`` subtree (`specs/15-memory-lcm.md` §5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_DREAMING_BACKFILL_DAYS,
    DEFAULT_DREAMING_CRON,
    DEFAULT_DREAMING_DIVERSITY_WEIGHT,
    DEFAULT_DREAMING_ENABLED,
    DEFAULT_DREAMING_LLM_RANKER_ENABLED,
    DEFAULT_DREAMING_MAX_PROMOTIONS_PER_RUN,
    DEFAULT_DREAMING_RECALL_WEIGHT,
    DEFAULT_DREAMING_RECENCY_WEIGHT,
    DEFAULT_DREAMING_SCORING_ADAPTIVE,
    DEFAULT_DREAMING_THRESHOLD,
    DEFAULT_LCM_AUTOCOMPACT_DISABLED,
    DEFAULT_LCM_CONDENSED_MIN_FANOUT,
    DEFAULT_LCM_CONDENSED_TARGET_TOKENS,
    DEFAULT_LCM_DEDUP_OVERLAP_THRESHOLD,
    DEFAULT_LCM_ENABLED,
    DEFAULT_LCM_FRESH_TAIL_COUNT,
    DEFAULT_LCM_INCREMENTAL_MAX_DEPTH,
    DEFAULT_LCM_LARGE_FILE_TOKEN_THRESHOLD,
    DEFAULT_LCM_LEAF_CHUNK_TOKENS,
    DEFAULT_LCM_LEAF_MIN_FANOUT,
    DEFAULT_LCM_LEAF_TARGET_TOKENS,
    DEFAULT_LCM_SMART_COLLAPSE_ENABLED,
    DEFAULT_LCM_SUMMARY_LANGUAGE,
    DEFAULT_LCM_TOPIC_SEARCH_MAX_SESSIONS,
    DEFAULT_LCM_UNCACHED_SUFFIX_CEILING_TOKENS,
    DEFAULT_LCM_UNCACHED_SUFFIX_FLOOR_TOKENS,
    DEFAULT_LCM_UNCACHED_SUFFIX_FRACTION,
    DEFAULT_MEMORY_PRE_COMPACTION_FLUSH_ENABLED,
    DEFAULT_USER_MODEL_BUMP_THROTTLE_MINUTES,
    DEFAULT_USER_MODEL_ENABLED,
    DEFAULT_USER_MODEL_MAX_FACTS,
    DEFAULT_USER_MODEL_MAX_INJECT_TOKENS,
    DEFAULT_USER_MODEL_TRIGGER_TIERS,
)


class MemoryPreCompactionFlushWorkspaceConfig(BaseModel):
    """``memory.pre_compaction_flush`` (`specs/15-memory-lcm.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_MEMORY_PRE_COMPACTION_FLUSH_ENABLED)
    model: str | None = None


class DreamingLlmRankerWorkspaceConfig(BaseModel):
    """``memory.dreaming.scoring.llm_ranker`` (`specs/31-memory-dreaming.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_DREAMING_LLM_RANKER_ENABLED)
    model: str | None = None


class DreamingScoringWorkspaceConfig(BaseModel):
    """``memory.dreaming.scoring`` — deterministic weights + optional ranker (`specs/31-memory-dreaming.md` §5)."""

    model_config = ConfigDict(extra="allow")

    recall_weight: float = Field(default=DEFAULT_DREAMING_RECALL_WEIGHT, ge=0.0, le=1.0)
    diversity_weight: float = Field(default=DEFAULT_DREAMING_DIVERSITY_WEIGHT, ge=0.0, le=1.0)
    recency_weight: float = Field(default=DEFAULT_DREAMING_RECENCY_WEIGHT, ge=0.0, le=1.0)
    adaptive: bool = Field(default=DEFAULT_DREAMING_SCORING_ADAPTIVE)
    llm_ranker: DreamingLlmRankerWorkspaceConfig | None = None


class DreamingWorkspaceConfig(BaseModel):
    """Optional Dreaming consolidation (`specs/31-memory-dreaming.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_DREAMING_ENABLED)
    promotion_mode: Literal["auto", "ack_required"] = "auto"
    cron: str = Field(default=DEFAULT_DREAMING_CRON, min_length=9)
    threshold: float = Field(default=DEFAULT_DREAMING_THRESHOLD, ge=0.0, le=1.0)
    max_promotions_per_run: int = Field(
        default=DEFAULT_DREAMING_MAX_PROMOTIONS_PER_RUN,
        ge=1,
        le=256,
    )
    backfill_days: int = Field(default=DEFAULT_DREAMING_BACKFILL_DAYS, ge=1, le=3650)
    scoring: DreamingScoringWorkspaceConfig | None = None


class UserModelWorkspaceConfig(BaseModel):
    """``memory.user_model`` Honcho-style inferred profile (`specs/32-memory-honcho.md` §3.2)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_USER_MODEL_ENABLED)
    extractor_model: str | None = None
    max_facts: int = Field(default=DEFAULT_USER_MODEL_MAX_FACTS, ge=1, le=512)
    max_inject_tokens: int = Field(default=DEFAULT_USER_MODEL_MAX_INJECT_TOKENS, ge=0)
    bump_throttle_minutes: int = Field(default=DEFAULT_USER_MODEL_BUMP_THROTTLE_MINUTES, ge=0)
    deny_topics: list[str] = Field(default_factory=list)
    trigger_tiers: list[str] = Field(default_factory=lambda: list(DEFAULT_USER_MODEL_TRIGGER_TIERS))


class MemoryWorkspaceSectionConfig(BaseModel):
    """Typed ``memory`` subtree — preserves unknown keys via ``extra="allow"``."""

    model_config = ConfigDict(extra="allow")

    pre_compaction_flush: MemoryPreCompactionFlushWorkspaceConfig | None = None
    dreaming: DreamingWorkspaceConfig | None = None
    user_model: UserModelWorkspaceConfig | None = None


class LcmWorkspaceConfig(BaseModel):
    """Typed ``lcm`` subtree (`specs/15-memory-lcm.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_LCM_ENABLED)
    fresh_tail_count: int = Field(default=DEFAULT_LCM_FRESH_TAIL_COUNT, ge=1)
    autocompact_disabled: bool = Field(default=DEFAULT_LCM_AUTOCOMPACT_DISABLED)
    summary_model: str | None = None
    leaf_target_tokens: int = Field(default=DEFAULT_LCM_LEAF_TARGET_TOKENS, ge=64)
    condensed_target_tokens: int = Field(default=DEFAULT_LCM_CONDENSED_TARGET_TOKENS, ge=64)
    leaf_chunk_tokens: int = Field(default=DEFAULT_LCM_LEAF_CHUNK_TOKENS, ge=256)
    leaf_min_fanout: int = Field(default=DEFAULT_LCM_LEAF_MIN_FANOUT, ge=1)
    condensed_min_fanout: int = Field(default=DEFAULT_LCM_CONDENSED_MIN_FANOUT, ge=1)
    incremental_max_depth: int = Field(default=DEFAULT_LCM_INCREMENTAL_MAX_DEPTH, ge=0)
    large_file_token_threshold: int = Field(default=DEFAULT_LCM_LARGE_FILE_TOKEN_THRESHOLD, ge=256)
    topic_search_max_sessions: int = Field(default=DEFAULT_LCM_TOPIC_SEARCH_MAX_SESSIONS, ge=1)
    summary_language: str = Field(default=DEFAULT_LCM_SUMMARY_LANGUAGE, min_length=1)
    dedup_overlap_threshold: float = Field(
        default=DEFAULT_LCM_DEDUP_OVERLAP_THRESHOLD,
        ge=0.0,
        le=1.0,
    )
    smart_collapse_enabled: bool = Field(default=DEFAULT_LCM_SMART_COLLAPSE_ENABLED)
    uncached_suffix_fraction: float = Field(
        default=DEFAULT_LCM_UNCACHED_SUFFIX_FRACTION,
        gt=0.0,
        le=1.0,
    )
    uncached_suffix_floor_tokens: int = Field(
        default=DEFAULT_LCM_UNCACHED_SUFFIX_FLOOR_TOKENS, ge=0
    )
    uncached_suffix_ceiling_tokens: int = Field(
        default=DEFAULT_LCM_UNCACHED_SUFFIX_CEILING_TOKENS, ge=1
    )
