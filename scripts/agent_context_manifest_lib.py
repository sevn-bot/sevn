"""Shared agent-context manifest build + validation helpers.

Module: scripts.agent_context_manifest_lib
Depends: json, pathlib, sevn.agent.context_manifest

Exports:
    build_schema_document — delegate to live manifest builder.
    load_golden_manifest — read committed ``infra/agent-context.manifest.json``.
    normalize_for_compare — strip volatile keys for golden diff.

Examples:
    >>> from pathlib import Path
    >>> isinstance(GOLDEN_PATH, Path)
    True
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sevn.agent.context_manifest import build_agent_context_manifest

REPO = Path(__file__).resolve().parents[1]
GOLDEN_PATH = REPO / "infra" / "agent-context.manifest.json"
META_SCHEMA_PATH = REPO / "infra" / "agent-context.schema.meta.json"

__all__ = [
    "GOLDEN_PATH",
    "META_SCHEMA_PATH",
    "build_schema_document",
    "load_golden_manifest",
    "normalize_for_compare",
]


def build_schema_document() -> dict[str, Any]:
    """Build the live agent-context manifest for golden emission or verify.

    Returns:
        dict[str, Any]: Full manifest document from :func:`build_agent_context_manifest`.

    Examples:
        >>> doc = build_schema_document()
        >>> doc["schema_version"]
        1
    """
    return build_agent_context_manifest()


def normalize_for_compare(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy suitable for golden diff (drop volatile timestamp and git stamp).

    Args:
        doc (dict[str, Any]): Full manifest document.

    Returns:
        dict[str, Any]: Normalized document without ``generated_at`` or ``git_commit``.

    Examples:
        >>> normalized = normalize_for_compare({"generated_at": "x", "git_commit": "y", "a": 1})
        >>> "generated_at" not in normalized and "git_commit" not in normalized
        True
    """
    out = dict(doc)
    out.pop("generated_at", None)
    out.pop("git_commit", None)
    return out


def load_golden_manifest() -> dict[str, Any]:
    """Load the committed golden manifest from :data:`GOLDEN_PATH`.

    Returns:
        dict[str, Any]: Parsed golden JSON document.

    Examples:
        >>> isinstance(load_golden_manifest(), dict)  # doctest: +SKIP
        True
    """
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
