"""Telegram Channels sub-tab automation (onboarding comprehensive setup W5)."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sevn.onboarding.telegram_automation import (
    TelegramBotExtract,
    _eval_bool,
    extract_bot_token_from_text,
    extract_bot_username_from_text,
    normalize_bot_username,
    run_create_new_bot,
    run_lookup_existing_bot,
    suggest_owner_user_id_from_text,
)


def test_eval_bool_coerces_cdp_strings() -> None:
    """Login probe accepts stringified true/false from CDP evaluate."""
    assert _eval_bool("true") is True
    assert _eval_bool("false") is False
    assert _eval_bool(True) is True


def test_extract_bot_token_from_text() -> None:
    """W5.2 — BotFather token regex."""
    text = (
        "Done! Use this token to access the HTTP API:\n123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    )
    assert extract_bot_token_from_text(text) == "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def test_extract_bot_username_from_text() -> None:
    """W5.2 — username parsed from BotFather reply."""
    assert (
        extract_bot_username_from_text("Congratulations! @my_sevn_bot is ready.") == "my_sevn_bot"
    )


def test_normalize_bot_username_strips_at() -> None:
    """W5.3 — username field normalisation."""
    assert normalize_bot_username("@MySevnBot") == "mysevnbot"


def test_normalize_bot_username_rejects_short() -> None:
    """W5.3 — invalid usernames raise."""
    with pytest.raises(ValueError, match="bot username"):
        normalize_bot_username("ab")


def test_suggest_owner_user_id_from_text() -> None:
    """W5.2 — optional owner id hint from page text."""
    assert suggest_owner_user_id_from_text("Your Id: 123456789") == "123456789"


def test_validate_field_bot_username_required_when_not_create_new() -> None:
    """W5.3 — server-side validation for lookup mode."""
    from sevn.onboarding.web_app import _validate_field

    async def _run() -> None:
        ok, _msg = await _validate_field(
            "wizard.telegram_bot_username",
            "",
            context={"wizard.telegram_create_new_bot": False},
        )
        assert ok is False
        ok2, _msg2 = await _validate_field(
            "wizard.telegram_bot_username",
            "my_sevn_bot",
            context={"wizard.telegram_create_new_bot": False},
        )
        assert ok2 is True
        ok3, _msg3 = await _validate_field(
            "wizard.telegram_bot_username",
            "",
            context={"wizard.telegram_create_new_bot": True},
        )
        assert ok3 is True

    asyncio.run(_run())


def test_validate_field_bot_name_required_when_create_new() -> None:
    """W5.3 — bot display name required for create-new mode."""
    from sevn.onboarding.web_app import _validate_field

    async def _run() -> None:
        ok, _msg = await _validate_field(
            "wizard.telegram_bot_name",
            "",
            context={"wizard.telegram_create_new_bot": True},
        )
        assert ok is False
        ok2, _msg2 = await _validate_field(
            "wizard.telegram_bot_name",
            "alexstestee",
            context={"wizard.telegram_create_new_bot": True},
        )
        assert ok2 is True
        ok3, _msg3 = await _validate_field(
            "wizard.telegram_bot_name",
            "",
            context={"wizard.telegram_create_new_bot": False},
        )
        assert ok3 is True

    asyncio.run(_run())


def test_wizard_html_channels_sub_nav() -> None:
    """W5.1 / W5.6 — Telegram sub-tab and Discord/Slack placeholders."""
    from importlib import resources

    html = (resources.files("sevn.onboarding") / "web_wizard" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'class="channel-sub-nav"' in html
    assert 'data-channel-tab="telegram"' in html
    assert 'data-channel-tab="discord"' in html
    assert 'data-channel-tab="slack"' in html
    assert 'data-field-id="wizard.telegram_create_new_bot"' in html
    assert 'data-field-id="wizard.telegram_bot_name"' in html
    assert 'id="btn-telegram-login"' in html
    assert 'id="btn-telegram-my-api"' in html


@pytest.fixture(autouse=True)
def _cleanup_browser_singleton() -> Any:
    """Reset browser session between tests."""
    from sevn.onboarding import browser_automation as ba

    yield
    ba.reset_browser_session_for_tests()


def test_telegram_login_endpoint_mocked() -> None:
    """W5.4 — login route opens Telegram Web via browser session."""
    from sevn.onboarding.web_app import create_onboarding_app

    tab_info = {"target_id": "t1", "url": "https://web.telegram.org/k/", "title": "TG"}
    mock_session = MagicMock()
    mock_session.running = True
    mock_session.status_payload.return_value = {"running": True, "steps": []}
    with (
        patch(
            "sevn.onboarding.web_app.get_browser_session",
            return_value=mock_session,
        ),
        patch(
            "sevn.onboarding.web_app.open_telegram_web",
            new_callable=AsyncMock,
            return_value=tab_info,
        ),
        patch(
            "sevn.onboarding.web_app.wait_for_login",
            new_callable=AsyncMock,
        ),
    ):
        client = TestClient(create_onboarding_app("tok"))
        res = client.post("/api/telegram/login", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True


def test_telegram_automate_stores_credentials_mocked() -> None:
    """W5.2 / W5.5 — automate route stores token without echoing in logs."""
    from sevn.onboarding.web_app import create_onboarding_app

    extract = TelegramBotExtract(
        bot_token="123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        bot_username="my_sevn_bot",
        owner_user_id="987654321",
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
            "sevn.onboarding.web_app.run_create_new_bot",
            new_callable=AsyncMock,
            return_value=extract,
        ),
        patch(
            "sevn.onboarding.web_app.store_wizard_credentials",
            new_callable=AsyncMock,
            return_value={"SEVN_TELEGRAM_BOT_TOKEN": True},
        ),
    ):
        client = TestClient(create_onboarding_app("tok"))
        res = client.post(
            "/api/telegram/automate",
            headers={"X-Onboard-Token": "tok"},
            json={"create_new": True, "display_name": "Test Bot"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["token_stored"] is True
    assert body["bot_username"] == "my_sevn_bot"
    assert body["bot_token"] == extract.bot_token


class _FakeBotFatherChat:
    """Scripted BotFather/getIDsBot chat replying to the latest sent command."""

    def __init__(self) -> None:
        self.last = ""
        self.count = 0

    async def send_keys(self, text: str) -> None:
        if text.strip():
            self.last = text.strip()
            self.count += 1

    async def click(self) -> None:
        return None

    def evaluate(self, js: str, await_promise: bool = False) -> object:
        if "getBoundingClientRect" in js and "column-left" in js:
            return True
        if "querySelectorAll('.bubble.is-in').length" in js:
            return self.count
        if ".bubble.is-in" in js and "textContent" in js:
            return self._reply()
        return self._reply()

    def _reply(self) -> str:
        sent = self.last
        if sent == "/newbot":
            return "Alright, a new bot. How are we going to call it? Please choose a name for your bot."
        if sent == "/start":
            return "\U0001f464 You\n\u251c id: 987654321\n\u251c is_bot: false"
        if sent == "/token":
            return "Choose a bot to receive its token."
        if sent.startswith("@"):
            return f"Token for {sent}:\n123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
        if sent.endswith("_bot"):
            return (
                "Done! Congratulations on your new bot. "
                "Use this token to access the HTTP API: "
                "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
            )
        return "Good. Now let's choose a username for your bot."


def _fake_session(chat: _FakeBotFatherChat) -> MagicMock:
    from sevn.onboarding.browser_automation import BrowserSession

    session = MagicMock(spec=BrowserSession)
    session.open_url = AsyncMock()
    session._steps = []

    def _record_step(label: str, *, state: str = "done") -> None:
        session._steps.append({"label": label, "state": state, "ts": 0.0})

    session._record_step = _record_step
    tab = MagicMock()

    async def _evaluate(js: str, await_promise: bool = False) -> object:
        return chat.evaluate(js, await_promise)

    tab.evaluate = _evaluate
    tab.select = AsyncMock(return_value=chat)
    tab.send = AsyncMock()
    session._resolve_tab = MagicMock(return_value=tab)
    return session


def test_run_create_new_bot_mocked_session() -> None:
    """W5.2 — create flow waits for each fresh reply then parses token + owner id."""
    session = _fake_session(_FakeBotFatherChat())

    async def _run() -> None:
        result = await run_create_new_bot(session, display_name="Test Bot")
        assert result.bot_token.startswith("123456789:")
        assert result.bot_username == "test_bot"
        assert result.owner_user_id == "987654321"

    asyncio.run(_run())


def test_run_lookup_existing_bot_mocked_session() -> None:
    """W5.3 — lookup flow uses /token and username."""
    session = _fake_session(_FakeBotFatherChat())

    async def _run() -> None:
        result = await run_lookup_existing_bot(session, bot_username="existing_bot")
        assert result.bot_username == "existing_bot"
        assert ":" in result.bot_token

    asyncio.run(_run())


@pytest.mark.onboard_e2e
@pytest.mark.skipif(
    os.environ.get("SEVN_ONBOARD_E2E") != "1",
    reason="Set SEVN_ONBOARD_E2E=1 for live onboarding Telegram smoke",
)
def test_telegram_automate_live_smoke_skipped_by_default() -> None:
    """W5.7 — optional live smoke (manual / CI with SEVN_ONBOARD_E2E=1)."""
    from sevn.onboarding.web_app import create_onboarding_app

    client = TestClient(create_onboarding_app("tok"))
    res = client.get("/api/browser/status", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200
