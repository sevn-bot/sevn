"""Trace redaction JSON helpers for operator toggles (`specs/04-tracing.md` §2.5).

Module: sevn.agent.tracing.redaction_config
Depends: sevn.config.defaults
Exports:
    apply_trace_redaction_to_sevn_doc — sync ``tracing.redaction`` for menu toggles.
    effective_trace_redaction_enabled_from_doc — resolve enabled flag from raw ``sevn.json``.
Examples:
    >>> from sevn.agent.tracing.redaction_config import apply_trace_redaction_to_sevn_doc
    >>> doc: dict[str, object] = {}
    >>> apply_trace_redaction_to_sevn_doc(doc, enabled=True)
    >>> doc["tracing"]["redaction"]["enabled"]
    True
"""

from __future__ import annotations

from typing import Any, Final

from sevn.config.defaults import (
    DEFAULT_TRACE_REDACTION_DENY_KEYS,
    DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS,
    DEFAULT_TRACE_REDACTION_ENABLED,
)

TRACE_USAGE_METRIC_ATTR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "tokens_in",
        "tokens_out",
    },
)


def effective_trace_redaction_enabled_from_doc(doc: dict[str, Any]) -> bool:
    """Return ``tracing.redaction.enabled`` from a raw ``sevn.json`` document.

    Args:
        doc (dict[str, Any]): Parsed ``sevn.json`` root object.

    Returns:
        bool: Explicit flag when present, else :data:`DEFAULT_TRACE_REDACTION_ENABLED`.

    Examples:
        >>> effective_trace_redaction_enabled_from_doc({})
        True
        >>> effective_trace_redaction_enabled_from_doc(
        ...     {"tracing": {"redaction": {"enabled": False}}},
        ... )
        False
    """
    tracing = doc.get("tracing")
    if not isinstance(tracing, dict):
        return DEFAULT_TRACE_REDACTION_ENABLED
    redaction = tracing.get("redaction")
    if not isinstance(redaction, dict):
        return DEFAULT_TRACE_REDACTION_ENABLED
    enabled = redaction.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    return DEFAULT_TRACE_REDACTION_ENABLED


def apply_trace_redaction_to_sevn_doc(doc: dict[str, Any], *, enabled: bool) -> None:
    """Write ``tracing.redaction`` for Telegram menu toggles (enabled + deny lists).

    When enabling, applies shipped deny keys/patterns that preserve token-usage
    metrics (see :data:`TRACE_USAGE_METRIC_ATTR_KEYS`). When disabling, clears
    deny lists so the next enable restores the canonical policy.

    Args:
        doc (dict[str, Any]): ``sevn.json`` root (mutated in place).
        enabled (bool): Target redaction on/off state.

    Examples:
        >>> doc: dict[str, object] = {}
        >>> apply_trace_redaction_to_sevn_doc(doc, enabled=True)
        >>> doc["tracing"]["redaction"]["enabled"]
        True
        >>> "token" not in doc["tracing"]["redaction"]["deny_keys"]
        True
        >>> apply_trace_redaction_to_sevn_doc(doc, enabled=False)
        >>> doc["tracing"]["redaction"]["deny_keys"]
        []
    """
    tracing = doc.get("tracing")
    if not isinstance(tracing, dict):
        tracing = {}
        doc["tracing"] = tracing
    if enabled:
        tracing["redaction"] = {
            "enabled": True,
            "deny_keys": list(DEFAULT_TRACE_REDACTION_DENY_KEYS),
            "deny_value_patterns": list(DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS),
        }
        return
    tracing["redaction"] = {
        "enabled": False,
        "deny_keys": [],
        "deny_value_patterns": [],
    }


__all__ = [
    "TRACE_USAGE_METRIC_ATTR_KEYS",
    "apply_trace_redaction_to_sevn_doc",
    "effective_trace_redaction_enabled_from_doc",
]
