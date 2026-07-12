"""Pydantic models for ``user_model.json`` (`specs/32-memory-honcho.md` §2.1).

Module: sevn.memory.user_model.models
Depends: pydantic

Exports:
    InferredFact — one inferred preference row stored on disk.
    UserProfile — root JSON document for the Honcho-style profile.

Examples:
    >>> from datetime import UTC, datetime
    >>> InferredFact(
    ...     id="1",
    ...     topic="lang",
    ...     value="Python",
    ...     confidence="high",
    ...     last_observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    ... ).topic
    'lang'
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class InferredFact(BaseModel):
    """One inferred row; profile never stores raw transcript bytes."""

    id: str
    topic: str
    value: str
    confidence: Literal["low", "medium", "high"]
    source_session_ids: list[str] = Field(default_factory=list, max_length=5)
    last_observed_at: datetime
    superseded_by_id: str | None = None

    @field_validator("last_observed_at")
    @classmethod
    def _utc_naive_ok(cls, v: datetime) -> datetime:
        """Normalise tz-aware datetimes to UTC for stable JSON round-trips.

        Args:
            v (datetime): Parsed timestamp.

        Returns:
            datetime: UTC-normalised value.

        Examples:
            >>> from datetime import UTC, datetime
            >>> InferredFact(
            ...     id="a",
            ...     topic="t",
            ...     value="v",
            ...     confidence="high",
            ...     last_observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ... ).last_observed_at.tzinfo
            datetime.timezone.utc
        """

        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class UserProfile(BaseModel):
    """Persisted inferred operator profile for one workspace."""

    workspace_id: str
    updated_at: datetime
    schema_version: int = 1
    facts: list[InferredFact] = Field(default_factory=list)

    @field_validator("updated_at")
    @classmethod
    def _utc_updated(cls, v: datetime) -> datetime:
        """UTC-normalise ``updated_at`` (see ``InferredFact``).

        Args:
            v (datetime): Parsed timestamp.

        Returns:
            datetime: UTC-normalised value.

        Examples:
            >>> from datetime import UTC, datetime
            >>> UserProfile(
            ...     workspace_id="w",
            ...     updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ... ).updated_at.tzinfo
            datetime.timezone.utc
        """

        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


__all__ = ["InferredFact", "UserProfile"]
