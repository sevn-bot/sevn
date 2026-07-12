"""Honcho-style inferred operator profile (`specs/32-memory-honcho.md`).

Module: sevn.memory.user_model
Depends: pydantic, httpx transport callers; **must not** import ``channels``.

Exports:
    InferredFact — one inferred preference row.
    UserProfile — persisted JSON document model.
    UserModelStore — atomic JSON persistence.
    UserModelMerger — merge + cap rules.
    UserModelExtractor — structured LLM extraction via ``Transport``.
    UserModelControl — promote / delete / suppress owner operations.
    UserModelExtractionQueue — per-workspace serialized extraction queue.
    schedule_user_model_extraction — enqueue post-reply extraction job.
    USER_MODEL_PROMPT_REV — pinned extractor prompt revision.
    render_profile_block — Triager personality breakpoint text.
    personality_bump_allowed — throttle helper for ``personality_version``.
    topic_denied — literal-substring deny_topics helper.

Examples:
    >>> from sevn.memory.user_model import UserModelMerger
    >>> isinstance(UserModelMerger(), UserModelMerger)
    True
"""

from __future__ import annotations

from sevn.memory.user_model.control import UserModelControl
from sevn.memory.user_model.deny_topics import topic_denied
from sevn.memory.user_model.extractor import UserModelExtractor
from sevn.memory.user_model.merger import UserModelMerger
from sevn.memory.user_model.models import InferredFact, UserProfile
from sevn.memory.user_model.queue import (
    USER_MODEL_PROMPT_REV,
    UserModelExtractionQueue,
    schedule_user_model_extraction,
)
from sevn.memory.user_model.renderer import render_profile_block
from sevn.memory.user_model.store import UserModelStore
from sevn.memory.user_model.throttle import personality_bump_allowed

__all__ = [
    "USER_MODEL_PROMPT_REV",
    "InferredFact",
    "UserModelControl",
    "UserModelExtractionQueue",
    "UserModelExtractor",
    "UserModelMerger",
    "UserModelStore",
    "UserProfile",
    "personality_bump_allowed",
    "render_profile_block",
    "schedule_user_model_extraction",
    "topic_denied",
]
