"""Pairing store unit tests (Wave M1)."""

from __future__ import annotations

from pathlib import Path

from sevn.gateway.pairing import PairingStore


def test_pairing_generate_and_approve(tmp_path: Path) -> None:
    store = PairingStore(tmp_path)
    code = store.generate_code("telegram", "42", user_name="Alex")
    assert code is not None
    assert len(code) == 8
    assert not store.is_approved("telegram", "42")
    result = store.approve_code("telegram", code)
    assert result is not None
    assert result["user_id"] == "42"
    assert store.is_approved("telegram", "42")


def test_pairing_invalid_code_records_failure(tmp_path: Path) -> None:
    store = PairingStore(tmp_path)
    assert store.approve_code("telegram", "NOTVALID") is None
    pending = store.list_pending("telegram")
    assert pending == []
