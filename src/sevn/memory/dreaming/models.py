"""Pydantic payloads for Dreaming runs (`specs/31-memory-dreaming.md` §2.1, §3.2).

``PromotionMode`` is ``Literal["auto", "ack_required"]`` for manifests and configs.

Module: sevn.memory.dreaming.models
Depends: pydantic

Exports:
    DreamingCandidate — scored row promoted or queued.
    DreamingRunResult — structured engine output.
    MemoryMdAnchor — byte span inside ``MEMORY.md``.
    PromotedManifestRow — one rollback row.
    PromotedBatchManifest — on-disk promoted batch JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PromotionMode = Literal["auto", "ack_required"]


class DreamingCandidate(BaseModel):
    """One scored unit — stable id within a run."""

    candidate_id: str
    topic: str
    value: str
    score: float = Field(ge=0.0, le=1.0)
    source_keys: list[str] = Field(default_factory=list)
    reasons: dict[str, float] = Field(
        default_factory=dict,
        description="Explainability payload, e.g. recall_weighted, diversity, recency.",
    )


class DreamingRunResult(BaseModel):
    """Structured output of a Dreaming pass."""

    run_id: str
    mode: PromotionMode
    promoted: list[DreamingCandidate]
    skipped: list[tuple[DreamingCandidate, str]]
    dreams_md_append: str
    promoted_manifest_path: Path


class MemoryMdAnchor(BaseModel):
    """Line range + content hash for ``MEMORY.md`` rollback (`specs/31-memory-dreaming.md` §3.2)."""

    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    content_sha256: str = Field(min_length=64, max_length=64)
    byte_start: int | None = Field(default=None, ge=0)
    byte_end: int | None = Field(default=None, ge=0)


class PromotedManifestRow(BaseModel):
    """Single promoted line manifest row."""

    topic: str
    value: str
    score: float
    source_keys: list[str] = Field(default_factory=list)
    memory_md_anchor: MemoryMdAnchor


class PromotedBatchManifest(BaseModel):
    """On-disk ``promoted/<run_id>.json`` — batch rollback uses pre/post file sizes."""

    run_id: str
    mode: PromotionMode
    memory_md_pre_bytes: int = Field(ge=0)
    memory_md_post_bytes: int = Field(ge=0)
    rows: list[PromotedManifestRow] = Field(default_factory=list)
