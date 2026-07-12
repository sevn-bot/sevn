"""Regression tests for :mod:`sevn.gateway.workspace_config_io`.

Covers the gateway ``/config`` menu-toggle write path: an in-place runtime
mutation must validate the document structurally yet tolerate a pre-existing,
unrelated provider-credential gap (e.g. ``triager = minimax/MiniMax-M3`` whose
key resolves at request time via the egress proxy). Blocking on it left every
``/config`` button silently failing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.gateway.workspace_config_io import mutate_sevn_json, set_nested


def _doc_with_uncredentialed_minimax_triager() -> dict[str, object]:
    """Build a structurally valid doc whose assigned triager has no static key."""
    return {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "providers": {
            "minimax": {"base_url": "https://api.minimax.io/anthropic/v1"},
            "tier_default": {"triager": "minimax/MiniMax-M3"},
            "use_main_model_for_all": True,
        },
    }


def _write_doc(tmp_path: Path, doc: dict[str, object]) -> Path:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(json.dumps(doc), encoding="utf-8")
    return sevn_json


def test_toggle_succeeds_despite_missing_provider_credential(tmp_path: Path) -> None:
    """A ``cfg:toggle`` write must not fail on a pre-existing credential gap."""
    sevn_json = _write_doc(tmp_path, _doc_with_uncredentialed_minimax_triager())

    out = mutate_sevn_json(
        sevn_json,
        lambda d: set_nested(d, "channels.telegram.show_routing", True),
    )

    assert out["channels"]["telegram"]["show_routing"] is True
    persisted = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert persisted["channels"]["telegram"]["show_routing"] is True


def test_toggle_still_rejects_structurally_invalid_document(tmp_path: Path) -> None:
    """Structural validation (schema version) still gates the write."""
    doc = _doc_with_uncredentialed_minimax_triager()
    sevn_json = _write_doc(tmp_path, doc)

    with pytest.raises(Exception):  # noqa: B017,PT011 — schema-version guard raises
        mutate_sevn_json(sevn_json, lambda d: d.update({"schema_version": 999}))


def test_opt_in_credential_check_rejects_missing_key(tmp_path: Path) -> None:
    """Passing ``check_provider_credentials=True`` restores the strict D7 gate."""
    sevn_json = _write_doc(tmp_path, _doc_with_uncredentialed_minimax_triager())

    with pytest.raises(ValueError, match="credential not configured"):
        mutate_sevn_json(
            sevn_json,
            lambda d: set_nested(d, "channels.telegram.show_routing", True),
            check_provider_credentials=True,
        )
