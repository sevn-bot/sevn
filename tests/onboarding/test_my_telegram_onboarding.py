"""my.telegram.org API automation tests for onboarding wizard."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sevn.onboarding.my_telegram_automation import (
    MyTelegramApiExtract,
    extract_api_hash_from_text,
    extract_api_id_from_text,
    normalize_phone,
    run_fetch_my_telegram_api,
)


def test_extract_api_id_from_text() -> None:
    """Parse api_id from my.telegram.org page text."""
    assert extract_api_id_from_text("App api_id: 12345678") == "12345678"


def test_extract_api_hash_from_text() -> None:
    """Parse api_hash hex from page text."""
    assert (
        extract_api_hash_from_text("App api_hash: abcdef0123456789abcdef0123456789")
        == "abcdef0123456789abcdef0123456789"
    )


def test_normalize_phone() -> None:
    """International phone normalisation."""
    assert normalize_phone("+15551234567") == "+15551234567"


def test_normalize_phone_rejects_invalid() -> None:
    """Invalid phones raise."""
    with pytest.raises(ValueError, match="phone"):
        normalize_phone("abc")


def test_telegram_my_api_endpoint_mocked() -> None:
    """my-api route stores api_id/api_hash without logging secrets."""
    from sevn.onboarding.web_app import create_onboarding_app

    extract = MyTelegramApiExtract(
        api_id="12345678",
        api_hash="abcdef0123456789abcdef0123456789",
        phone="+15551234567",
    )
    mock_session = MagicMock()
    mock_session.running = True
    mock_session.start = AsyncMock()
    mock_session.status_payload.return_value = {"steps": []}

    with (
        patch(
            "sevn.onboarding.web_app.get_browser_session",
            return_value=mock_session,
        ),
        patch(
            "sevn.onboarding.web_app.run_fetch_my_telegram_api",
            new_callable=AsyncMock,
            return_value=extract,
        ),
        patch(
            "sevn.onboarding.web_app.store_wizard_credentials",
            new_callable=AsyncMock,
            return_value={
                "SEVN_TELEGRAM_API_ID": True,
                "SEVN_TELEGRAM_API_HASH": True,
            },
        ),
    ):
        client = TestClient(create_onboarding_app("tok"))
        res = client.post(
            "/api/telegram/my-api",
            headers={"X-Onboard-Token": "tok"},
            json={"phone": "+15551234567"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["api_id"] == "12345678"
    assert body["api_stored"] is True


def test_telegram_my_api_skipped_on_rate_limit() -> None:
    """Rate-limited my.telegram.org returns skipped JSON and stops browser."""
    from sevn.onboarding.my_telegram_automation import MyTelegramSkipError
    from sevn.onboarding.web_app import create_onboarding_app

    mock_session = MagicMock()
    mock_session.running = True
    mock_session.start = AsyncMock()
    mock_session.stop = AsyncMock(return_value={"stopped": True})
    mock_session.status_payload.return_value = {"steps": []}

    with (
        patch(
            "sevn.onboarding.web_app.get_browser_session",
            return_value=mock_session,
        ),
        patch(
            "sevn.onboarding.web_app.run_fetch_my_telegram_api",
            new_callable=AsyncMock,
            side_effect=MyTelegramSkipError(
                "rate_limited",
                "my.telegram.org rate-limited (too many tries) — skipping this optional step",
            ),
        ),
    ):
        client = TestClient(create_onboarding_app("tok"))
        res = client.post(
            "/api/telegram/my-api",
            headers={"X-Onboard-Token": "tok"},
            json={},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["skipped"] is True
    assert body["skip_reason"] == "rate_limited"
    mock_session.stop.assert_awaited_once()


def test_run_fetch_my_telegram_api_mocked_session() -> None:
    """Fetch flow reads existing app credentials from mocked DOM."""
    from sevn.onboarding.browser_automation import BrowserSession
    from sevn.onboarding.my_telegram_automation import _CURRENT_URL_JS, _READ_APPS_JS

    apps_payload = json.dumps(
        {
            "apiId": "87654321",
            "apiHash": "abcdef0123456789abcdef0123456789",
            "hasCreds": True,
            "createForm": False,
            "url": "https://my.telegram.org/apps",
            "needsCode": False,
            "needsPhone": False,
        }
    )

    session = MagicMock(spec=BrowserSession)
    session.open_url = AsyncMock()
    session.extract_text = AsyncMock(return_value="")
    session._record_step = MagicMock()
    session._steps = []
    tab = MagicMock()
    tab.evaluate = AsyncMock(
        side_effect=lambda js, await_promise=False: (
            "https://my.telegram.org/apps"
            if js == _CURRENT_URL_JS
            else apps_payload
            if js == _READ_APPS_JS
            else '{"needsPhone": false, "needsCode": false, "onAuth": false}'
        )
    )
    session._resolve_tab = MagicMock(return_value=tab)

    async def _run() -> None:
        result = await run_fetch_my_telegram_api(session, phone="+15551234567")
        assert result.api_id == "87654321"
        assert len(result.api_hash) == 32

    asyncio.run(_run())
    session.open_url.assert_called()
    first_url = session.open_url.call_args_list[0][0][0]
    assert "/apps" in first_url
    session._record_step.assert_any_call("mytelegram.session_reused")
    session._record_step.assert_any_call("mytelegram.use_existing_app")
