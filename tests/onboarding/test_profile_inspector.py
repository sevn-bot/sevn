"""Profile inspector API and row builder (onboarding comprehensive setup W7)."""

from __future__ import annotations

from importlib import resources

from fastapi.testclient import TestClient

from sevn.onboarding.profile_inspector import (
    build_profile_inspector_payload,
    format_inspector_value,
)
from sevn.onboarding.web_app import create_onboarding_app


def test_format_inspector_value_booleans() -> None:
    """Booleans render as on/off for the inspector table."""
    assert format_inspector_value(True) == "on"
    assert format_inspector_value(False) == "off"


def test_build_profile_inspector_includes_triager_and_capabilities() -> None:
    """Merged profile rows include model slot and capability defaults."""
    payload = build_profile_inspector_payload("good_value_osx")
    field_ids = {row["field_id"] for row in payload["rows"]}
    assert "providers.tier_default.triager" in field_ids
    assert "gateway.queue_mode" in field_ids
    assert "self_improve.enabled" in field_ids
    assert "sandbox.mode" in field_ids
    triager = next(r for r in payload["rows"] if r["field_id"] == "providers.tier_default.triager")
    assert triager["value"] == "minimax/MiniMax-M2.7"
    assert triager["tab"] == "Main model"


def test_api_profile_inspector_returns_rows() -> None:
    """``GET /api/profile-inspector`` returns read-only grouped rows."""
    client = TestClient(create_onboarding_app("test-token"))
    res = client.get(
        "/api/profile-inspector?profile_id=good_value_osx",
        headers={"X-Onboard-Token": "test-token"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["profile_id"] == "good_value_osx"
    assert isinstance(body["rows"], list)
    assert len(body["rows"]) > 10
    assert all({"tab", "field", "value", "explanation", "field_id"} <= set(r) for r in body["rows"])


def test_api_profile_inspector_rejects_skip() -> None:
    """Skip/custom is not a packaged profile fragment."""
    client = TestClient(create_onboarding_app("test-token"))
    res = client.get(
        "/api/profile-inspector?profile_id=skip",
        headers={"X-Onboard-Token": "test-token"},
    )
    assert res.status_code == 400


def test_wizard_html_profile_inspector_modal_read_only() -> None:
    """Modal markup has a table body and no form inputs (D12)."""
    html = (resources.files("sevn.onboarding") / "web_wizard" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="profile-inspector-modal"' in html
    assert 'id="profile-inspector-tbody"' in html
    modal_start = html.index('id="profile-inspector-modal"')
    modal_end = html.index('id="backup-repo-modal"')
    modal_block = html[modal_start:modal_end]
    assert "<input" not in modal_block
    assert "<select" not in modal_block
    assert "<textarea" not in modal_block


def test_app_js_profile_inspector_dblclick_and_api() -> None:
    """Profile cards wire double-click to the inspector API."""
    app_js = (resources.files("sevn.onboarding") / "web_wizard" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "openProfileInspector" in app_js
    assert "dblclick" in app_js
    assert "/api/profile-inspector" in app_js
    assert "hideProfileInspectorModal" in app_js
