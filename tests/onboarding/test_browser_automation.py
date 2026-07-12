"""Tests for onboarding browser automation — CDP mocks, no live Chrome."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sevn.onboarding.cdp_browser import CDPOnboardingBrowser


@pytest.fixture(autouse=True)
def _cleanup_browser_singleton() -> None:
    """Reset browser session between tests."""
    from sevn.onboarding import browser_automation as ba

    yield
    ba.reset_browser_session_for_tests()


def test_agpl_notice_endpoint_returns_cdp_engine() -> None:
    """Legacy AGPL route reports CDP engine with no notice."""
    from sevn.onboarding.web_app import create_onboarding_app

    client = TestClient(create_onboarding_app("tok"))
    res = client.get("/api/browser/agpl-notice", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200
    body = res.json()
    assert body["browser_engine"] == "cdp"


def test_browser_status_poll_before_start() -> None:
    """W2.3 — status endpoint reports idle session."""
    from sevn.onboarding.web_app import create_onboarding_app

    client = TestClient(create_onboarding_app("tok"))
    res = client.get("/api/browser/status", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200
    body = res.json()
    assert body["running"] is False
    assert isinstance(body["steps"], list)


def test_browser_start_stop_mocked_attach() -> None:
    """W2.3 — start/stop API routes delegate to the CDP browser session."""
    from sevn.onboarding.web_app import create_onboarding_app

    mock_session = MagicMock(spec=CDPOnboardingBrowser)
    mock_session.start = AsyncMock(
        return_value={"running": True, "browser_engine": "cdp", "tab_count": 1, "steps": []}
    )
    mock_session.stop = AsyncMock(
        return_value={"running": False, "browser_engine": "cdp", "steps": []}
    )
    mock_session.status_payload.return_value = {
        "running": True,
        "browser_engine": "cdp",
        "tab_count": 1,
        "steps": [],
    }

    with patch("sevn.onboarding.web_app.get_browser_session", return_value=mock_session):
        client = TestClient(create_onboarding_app("tok"))
        start = client.post(
            "/api/browser/start",
            headers={"X-Onboard-Token": "tok"},
            json={"cdp_url": "http://127.0.0.1:9222"},
        )
    assert start.status_code == 200, start.text
    assert start.json()["running"] is True
    assert start.json()["browser_engine"] == "cdp"
    status = client.get("/api/browser/status", headers={"X-Onboard-Token": "tok"})
    assert status.json()["tab_count"] >= 0
    stop = client.post("/api/browser/stop", headers={"X-Onboard-Token": "tok"})
    assert stop.status_code == 200
    assert stop.json()["running"] is False


def test_get_browser_session_returns_cdp_implementation() -> None:
    """Default factory returns CDPOnboardingBrowser without env toggle."""
    from sevn.onboarding import browser_automation as ba

    ba.reset_browser_session_for_tests()
    session = ba.get_browser_session()
    assert isinstance(session, CDPOnboardingBrowser)


def test_resolve_start_request_defaults_profile() -> None:
    """Default onboarding Chrome profile lives under operator home."""
    from sevn.onboarding.browser_automation import resolve_start_request

    req = resolve_start_request()
    assert req.user_data_dir is not None
    assert req.user_data_dir.endswith("onboarding-chrome-profile")
