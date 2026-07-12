"""Tests for trace redaction ``sevn.json`` helpers."""

from __future__ import annotations

from sevn.agent.tracing.redaction_config import (
    apply_trace_redaction_to_sevn_doc,
    effective_trace_redaction_enabled_from_doc,
)
from sevn.config.defaults import (
    DEFAULT_TRACE_REDACTION_DENY_KEYS,
    DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS,
)


def test_effective_trace_redaction_enabled_defaults_true() -> None:
    assert effective_trace_redaction_enabled_from_doc({}) is True


def test_apply_trace_redaction_enable_writes_canonical_deny_lists() -> None:
    doc: dict[str, object] = {}
    apply_trace_redaction_to_sevn_doc(doc, enabled=True)
    redaction = doc["tracing"]["redaction"]  # type: ignore[index]
    assert redaction["enabled"] is True
    assert redaction["deny_keys"] == list(DEFAULT_TRACE_REDACTION_DENY_KEYS)
    assert redaction["deny_value_patterns"] == list(DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS)
    assert "token" not in redaction["deny_keys"]


def test_apply_trace_redaction_disable_clears_deny_lists() -> None:
    doc: dict[str, object] = {
        "tracing": {
            "redaction": {
                "enabled": True,
                "deny_keys": list(DEFAULT_TRACE_REDACTION_DENY_KEYS),
                "deny_value_patterns": list(DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS),
            },
        },
    }
    apply_trace_redaction_to_sevn_doc(doc, enabled=False)
    redaction = doc["tracing"]["redaction"]  # type: ignore[index]
    assert redaction["enabled"] is False
    assert redaction["deny_keys"] == []
    assert redaction["deny_value_patterns"] == []
