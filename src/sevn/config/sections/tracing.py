"""Tracing subtree models for ``sevn.json``.

Module: sevn.config.sections.tracing
Depends: pydantic, sevn.config.defaults

Exports:
    TraceSinkEntry — one sink in ``tracing.sinks``.
    TraceRedactionConfig — ``tracing.redaction`` deny rules (`specs/04-tracing.md` §2.5).
    TracingConfig — ``tracing`` block subset.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_TRACE_REDACTION_DENY_KEYS,
    DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS,
    DEFAULT_TRACE_REDACTION_ENABLED,
)


class TraceSinkEntry(BaseModel):
    """One trace sink descriptor (``tracing.sinks[]``)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    sink_type: str = Field(alias="type")
    path: str | None = None
    token_ref: str | None = None
    project: str | None = None
    endpoint: str | None = None
    headers: dict[str, str] | None = None


class TraceRedactionConfig(BaseModel):
    """``tracing.redaction`` — single global policy before sink fan-out."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_TRACE_REDACTION_ENABLED
    deny_keys: list[str] = Field(default_factory=lambda: list(DEFAULT_TRACE_REDACTION_DENY_KEYS))
    deny_value_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS),
    )


class TracingConfig(BaseModel):
    """Trace retention and sink list."""

    model_config = ConfigDict(extra="allow")

    retention_days: int | None = None
    sinks: list[TraceSinkEntry] | None = None
    redaction: TraceRedactionConfig | None = None
