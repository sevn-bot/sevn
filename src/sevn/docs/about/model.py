"""Pydantic frontmatter model for about-docs (`about-sevn.bot/_docsys/README.md` §2).

Module: sevn.docs.about.model
Depends: datetime, json, pathlib, re, typing, pydantic

Exports:
    Interface — one public symbol row for spec docs.
    AboutDoc — validated YAML frontmatter for PRD/spec markdown.
    export_json_schema — Draft 2020-12 JSON Schema matching ``about-docs.schema.json``.

Examples:
    >>> from sevn.docs.about.model import AboutDoc
    >>> AboutDoc.model_validate(
    ...     {
    ...         "id": "spec-17-gateway",
    ...         "kind": "spec",
    ...         "title": "Gateway",
    ...         "status": "done",
    ...         "owner": "Alex",
    ...         "summary": "Turn spine.",
    ...         "last_updated": "2026-06-19",
    ...         "parent_prd": "prd-01-conversational-experience",
    ...         "sources": ["src/sevn/gateway/**"],
    ...     }
    ... ).id
    'spec-17-gateway'
"""

from __future__ import annotations

import json
import re
from datetime import date  # noqa: TC003 — Pydantic resolves ``last_updated: date`` at runtime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = r"^(prd|spec)-\d{2}-[a-z0-9-]+$"
PRD_ID_PATTERN = r"^prd-\d{2}-[a-z0-9-]+$"
SPEC_ID_PATTERN = r"^spec-\d{2}-[a-z0-9-]+$"

_ID_RE = re.compile(ID_PATTERN)
_PRD_ID_RE = re.compile(PRD_ID_PATTERN)


class Interface(BaseModel):
    """One public symbol row extracted from source AST."""

    model_config = ConfigDict(extra="forbid")

    name: str
    file: str
    symbol: str | None = None


class AboutDoc(BaseModel):
    """Validated YAML frontmatter for one about-doc markdown file."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["prd", "spec"]
    title: str
    status: Literal["draft", "scaffold", "ready", "done", "rejected"]
    owner: str
    summary: str = Field(max_length=200)
    last_updated: date
    fingerprint: str | None = None
    related: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    parent_prd: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    build_phase: str | None = None
    interfaces: list[Interface] = Field(default_factory=list)
    specs: list[str] = Field(default_factory=list)
    personas: list[str] = Field(default_factory=list)
    prd_profile: Literal["standard", "ai-native"] | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        """Ensure ``id`` matches :data:`ID_PATTERN`.

        Args:
            value (str): Candidate document id.

        Returns:
            str: Validated id.

        Examples:
            >>> AboutDoc._validate_id("spec-17-gateway")
            'spec-17-gateway'
        """
        if not _ID_RE.fullmatch(value):
            msg = f"id must match {ID_PATTERN!r}"
            raise ValueError(msg)
        return value

    @field_validator("related")
    @classmethod
    def _validate_related(cls, value: list[str]) -> list[str]:
        """Ensure every ``related`` entry matches :data:`ID_PATTERN`.

        Args:
            value (list[str]): Related doc ids.

        Returns:
            list[str]: Validated ids.

        Examples:
            >>> AboutDoc._validate_related(["spec-18-channel-telegram"])
            ['spec-18-channel-telegram']
        """
        for item in value:
            if not _ID_RE.fullmatch(item):
                msg = f"related id must match {ID_PATTERN!r}"
                raise ValueError(msg)
        return value

    @field_validator("depends_on")
    @classmethod
    def _validate_depends_on(cls, value: list[str]) -> list[str]:
        """Ensure every ``depends_on`` entry is a spec id.

        Args:
            value (list[str]): Dependency spec ids.

        Returns:
            list[str]: Validated ids.

        Examples:
            >>> AboutDoc._validate_depends_on(["spec-17-gateway"])
            ['spec-17-gateway']
        """
        for item in value:
            if not re.fullmatch(SPEC_ID_PATTERN, item):
                msg = f"depends_on id must match {SPEC_ID_PATTERN!r}"
                raise ValueError(msg)
        return value

    @field_validator("specs")
    @classmethod
    def _validate_specs(cls, value: list[str]) -> list[str]:
        """Ensure every ``specs`` entry is a spec id.

        Args:
            value (list[str]): Linked spec ids on PRD docs.

        Returns:
            list[str]: Validated ids.

        Examples:
            >>> AboutDoc._validate_specs(["spec-17-gateway"])
            ['spec-17-gateway']
        """
        for item in value:
            if not re.fullmatch(SPEC_ID_PATTERN, item):
                msg = f"specs id must match {SPEC_ID_PATTERN!r}"
                raise ValueError(msg)
        return value

    @field_validator("parent_prd")
    @classmethod
    def _validate_parent_prd(cls, value: str | None) -> str | None:
        """Ensure ``parent_prd`` is a PRD id or ``None``.

        Args:
            value (str | None): Parent PRD id.

        Returns:
            str | None: Validated id.

        Examples:
            >>> AboutDoc._validate_parent_prd("prd-01-conversational-experience")
            'prd-01-conversational-experience'
        """
        if value is None:
            return None
        if not _PRD_ID_RE.fullmatch(value):
            msg = f"parent_prd must match {PRD_ID_PATTERN!r}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_kind_fields(self) -> Self:
        """Apply PRD/spec field gating after base field validation.

        Returns:
            Self: Validated document.

        Examples:
            >>> from datetime import date
            >>> AboutDoc(
            ...     id="spec-17-gateway",
            ...     kind="spec",
            ...     title="Gateway",
            ...     status="done",
            ...     owner="Alex",
            ...     summary="Turn spine.",
            ...     last_updated=date(2026, 6, 19),
            ...     parent_prd="prd-01-conversational-experience",
            ...     sources=["src/sevn/gateway/**"],
            ... ).kind
            'spec'
        """
        if self.kind == "spec":
            if self.parent_prd is None:
                msg = "spec requires parent_prd"
                raise ValueError(msg)
            if not self.sources:
                msg = "spec requires non-empty sources"
                raise ValueError(msg)
            if self.specs or self.personas or self.prd_profile is not None:
                msg = "spec cannot include prd-only fields (specs, personas, prd_profile)"
                raise ValueError(msg)
        elif self.kind == "prd":
            if self.depends_on or self.build_phase or self.interfaces:
                msg = "prd cannot include spec-only fields (depends_on, build_phase, interfaces)"
                raise ValueError(msg)
        return self


def _default_schema_path() -> Path:
    """Return the checked-in about-docs JSON Schema path under the repo root.

    Returns:
        Path: ``about-sevn.bot/_docsys/about-docs.schema.json``.

    Examples:
        >>> p = _default_schema_path()
        >>> p.name == "about-docs.schema.json"
        True
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "about-sevn.bot" / "_docsys" / "about-docs.schema.json"
        if candidate.is_file():
            return candidate
    msg = "about-docs.schema.json not found under about-sevn.bot/_docsys/"
    raise FileNotFoundError(msg)


def export_json_schema() -> dict[str, Any]:
    """Return the Draft 2020-12 JSON Schema for :class:`AboutDoc` frontmatter.

    The exported document must match ``about-sevn.bot/_docsys/about-docs.schema.json``.
    Runtime validation uses :class:`AboutDoc`; the checked-in schema is the editor/CI
    parity gate (same pattern as ``make config-schema``).

    Returns:
        dict[str, Any]: JSON Schema object.

    Examples:
        >>> schema = export_json_schema()
        >>> schema["$schema"].endswith("/2020-12/schema")
        True
    """
    path = _default_schema_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "about-docs.schema.json must contain a JSON object"
        raise TypeError(msg)
    return raw


__all__ = [
    "ID_PATTERN",
    "PRD_ID_PATTERN",
    "AboutDoc",
    "Interface",
    "export_json_schema",
]
