"""Tests for Logfire export config helpers."""

from __future__ import annotations

from sevn.agent.tracing.logfire_config import (
    DEFAULT_LOGFIRE_TOKEN_REF,
    apply_logfire_export_to_sevn_doc,
    logfire_export_status_from_doc,
)


def test_apply_logfire_export_prepends_sink_and_keeps_local() -> None:
    doc: dict[str, object] = {
        "tracing": {
            "sinks": [
                {"type": "sqlite"},
                {"type": "jsonl_file", "path": ".sevn/traces/"},
            ],
        },
    }
    apply_logfire_export_to_sevn_doc(doc, enabled=True)
    status = logfire_export_status_from_doc(doc)
    assert status.enabled is True
    assert status.token_ref == DEFAULT_LOGFIRE_TOKEN_REF
    assert status.local_sinks == ("sqlite", "jsonl_file")
    sinks = doc["tracing"]["sinks"]  # type: ignore[index]
    assert isinstance(sinks, list)
    assert sinks[0]["type"] == "logfire"


def test_apply_logfire_export_logfire_only_drops_local_sinks() -> None:
    doc: dict[str, object] = {
        "tracing": {
            "sinks": [
                {"type": "sqlite"},
                {"type": "jsonl_file", "path": ".sevn/traces/"},
            ],
        },
    }
    apply_logfire_export_to_sevn_doc(doc, enabled=True, keep_local_sinks=False)
    status = logfire_export_status_from_doc(doc)
    assert status.enabled is True
    assert status.local_sinks == ()


def test_apply_logfire_export_disable_removes_sink() -> None:
    doc: dict[str, object] = {
        "tracing": {
            "sinks": [
                {"type": "logfire", "token_ref": DEFAULT_LOGFIRE_TOKEN_REF},
                {"type": "sqlite"},
            ],
        },
    }
    apply_logfire_export_to_sevn_doc(doc, enabled=False)
    status = logfire_export_status_from_doc(doc)
    assert status.enabled is False
    assert status.local_sinks == ("sqlite",)
