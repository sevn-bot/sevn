"""Onboarding profile catalog and fragment parity (`onboarding-comprehensive-setup` W10)."""

from __future__ import annotations

from importlib import resources

from fastapi.testclient import TestClient

from sevn.onboarding.profiles import (
    load_profile_catalog,
    load_profile_catalog_for_wizard,
    load_profile_fragment,
    profile_has_capabilities_defaults,
)
from sevn.onboarding.web_app import create_onboarding_app


def test_every_catalog_profile_has_capabilities_defaults() -> None:
    """W10.1 — every packaged fragment ships non-empty ``capabilities_defaults``."""
    for row in load_profile_catalog():
        pid = str(row["profile_id"])
        frag = load_profile_fragment(pid)
        defaults = frag.get("capabilities_defaults")
        assert isinstance(defaults, dict), pid
        assert defaults, pid
        assert profile_has_capabilities_defaults(pid)


def test_catalog_capabilities_summary_present() -> None:
    """W10.3 — each catalog row documents capability preset summary."""
    for row in load_profile_catalog():
        summary = str(row.get("capabilities_summary", "")).strip()
        assert summary, row.get("profile_id")


def test_wizard_catalog_marks_capabilities_ready() -> None:
    """W10.2 — meta API exposes ``capabilities_ready`` for selectable profiles."""
    rows = load_profile_catalog_for_wizard()
    ready = [r for r in rows if r.get("capabilities_ready")]
    assert len(ready) == len(load_profile_catalog())


def test_api_meta_profiles_capabilities_ready() -> None:
    """``GET /api/meta`` returns enriched profile rows."""
    client = TestClient(create_onboarding_app("test-token"))
    res = client.get("/api/meta", headers={"X-Onboard-Token": "test-token"})
    assert res.status_code == 200
    profiles = res.json()["profiles"]
    assert all(p.get("capabilities_ready") for p in profiles)
    assert all(str(p.get("capabilities_summary", "")).strip() for p in profiles)


def test_app_js_uses_capabilities_ready_gate() -> None:
    """Profile cards enable when ``capabilities_ready`` is true (not tag-only)."""
    app_js = (resources.files("sevn.onboarding") / "web_wizard" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "profileCapabilitiesReady" in app_js
    assert "capabilities_summary" in app_js


def test_good_value_docker_disables_browser_extra() -> None:
    """Docker value preset keeps Playwright browser off while CDP engine stays on."""
    frag = load_profile_fragment("good_value_docker")
    defaults = frag["capabilities_defaults"]
    assert defaults["extra.browser"] is False
    assert defaults["extra.browser_cdp"] is True
