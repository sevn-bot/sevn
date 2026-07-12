"""Tests for ``seed_tracing_defaults`` (`specs/04-tracing.md` §5.2)."""

from __future__ import annotations

import json
from pathlib import Path

from sevn.config.defaults import DEFAULT_TRACING_SINKS
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.seed import seed_tracing_defaults


def test_seed_tracing_defaults_writes_when_absent() -> None:
    doc: dict[str, object] = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    assert seed_tracing_defaults(doc) is True
    tracing = doc.get("tracing")
    assert isinstance(tracing, dict)
    assert tracing.get("sinks") == [dict(entry) for entry in DEFAULT_TRACING_SINKS]


def test_seed_tracing_defaults_preserves_explicit_empty_list() -> None:
    doc: dict[str, object] = {
        "schema_version": 1,
        "tracing": {"sinks": []},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    assert seed_tracing_defaults(doc) is False
    tracing = doc["tracing"]
    assert isinstance(tracing, dict)
    assert tracing.get("sinks") == []


def test_seed_tracing_defaults_preserves_custom_sinks() -> None:
    custom = [{"type": "sqlite"}]
    doc: dict[str, object] = {
        "schema_version": 1,
        "tracing": {"sinks": custom},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    assert seed_tracing_defaults(doc) is False
    tracing = doc["tracing"]
    assert isinstance(tracing, dict)
    assert tracing.get("sinks") == custom


def test_promote_draft_seeds_tracing_when_key_absent(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    draft = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    }
    write_draft(sevn_json, draft)
    promote_draft(sevn_json, backup_previous=False)
    promoted = json.loads(sevn_json.read_text(encoding="utf-8"))
    sinks = promoted.get("tracing", {}).get("sinks")
    assert sinks == [dict(entry) for entry in DEFAULT_TRACING_SINKS]
