"""PR #51 Discogs menu RED tests (green after W17)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.menu.menu_readiness import readiness_for_callback
from sevn.gateway.menu.menu_registry import match_menu_button_spec
from tests.gateway.test_discogs_menu import _build_router


@pytest.mark.xfail(reason="green after W17: discogs token resolves to C7.18", strict=False)
def test_discogs_user_token_callback_is_c7_18_not_c6_1b() -> None:
    spec = match_menu_button_spec("form:secret_wizard:discogs.user_token")
    assert spec is not None
    assert spec.spec_id == "C7.18"
    assert readiness_for_callback("form:secret_wizard:discogs.user_token") == "Ready"


@pytest.mark.xfail(reason="green after W17: C7.19 OAuth Ready", strict=False)
def test_discogs_oauth_start_is_ready() -> None:
    spec = match_menu_button_spec("form:discogs:oauth_start")
    assert spec is not None
    assert spec.spec_id == "C7.19"
    assert readiness_for_callback("form:discogs:oauth_start") == "Ready"
    # Must not rewrite to cfg:disabled:C7.19
    assert not readiness_for_callback("form:discogs:oauth_start").startswith("WIP")


@pytest.mark.xfail(reason="green after W17: registry asserts C7.18 spec_id", strict=False)
def test_menu_registry_discogs_token_spec_id() -> None:
    spec = match_menu_button_spec("form:secret_wizard:discogs.user_token")
    assert spec is not None
    assert spec.implemented is True
    assert spec.spec_id == "C7.18"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W17: wizard reloads workspace for whoami", strict=False)
async def test_user_token_wizard_reloads_workspace_for_whoami(tmp_path: Path) -> None:
    router, cap, _root, _sevn_json = _build_router(tmp_path)
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner",
            text="my-discogs-token",
            metadata={
                "callback_data": "form:secret_wizard:discogs.user_token",
                "callback_query_id": "cq-discogs-token",
                "chat_id": 42,
                "message_id": 100,
                "owner": True,
            },
        ),
    )
    await router.route_incoming(
        IncomingMessage(
            channel="telegram",
            user_id="owner",
            text="my-discogs-token",
            metadata={"chat_id": 42, "owner": True},
        ),
    )
    with patch(
        "sevn.skills.manager.SkillsManager.run_script",
        new=AsyncMock(return_value={"ok": True, "data": {"username": "dj-alex"}}),
    ):
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="owner",
                text="",
                metadata={
                    "callback_data": "act:discogs:whoami",
                    "callback_query_id": "cq-whoami",
                    "chat_id": 42,
                    "message_id": 101,
                    "owner": True,
                },
            ),
        )
    answers = dict(cap.answered)
    toast = answers.get("cq-whoami") or ""
    assert "Discogs" in toast or "dj-alex" in toast or "connected" in toast.lower()


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W17: act:discogs:whoami toast", strict=False)
async def test_discogs_whoami_toast(tmp_path: Path) -> None:
    router, cap, _root, _sevn_json = _build_router(tmp_path)
    with patch(
        "sevn.skills.manager.SkillsManager.run_script",
        new=AsyncMock(return_value={"ok": True, "data": {"username": "vinyl-fan"}}),
    ):
        await router.route_incoming(
            IncomingMessage(
                channel="telegram",
                user_id="owner",
                text="",
                metadata={
                    "callback_data": "act:discogs:whoami",
                    "callback_query_id": "cq-who",
                    "chat_id": 42,
                    "message_id": 50,
                    "owner": True,
                },
            ),
        )
    toast = dict(cap.answered).get("cq-who") or ""
    assert "vinyl-fan" in toast or "Discogs connected" in toast
