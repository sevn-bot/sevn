"""PR #47 browser/X ops RED upgrades (green after W13)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W13: assert_send_receive behavioral", strict=False)
async def test_telegram_checks_assert_send_receive_transcript() -> None:
    """Upgrade callable-only probe: drive assert_send_receive and assert transcript."""
    from sevn.browser.recipes import telegram_checks

    tg = MagicMock()
    tg.send = AsyncMock(return_value=None)
    tg.read = AsyncMock(return_value="hello from bot\nping-123")
    out = await telegram_checks.assert_send_receive(tg, chat="Saved Messages", text="ping-123")
    assert isinstance(out, dict)
    assert out.get("sent") is True
    assert "ping-123" in str(out.get("text", ""))
    tg.send.assert_awaited()


@pytest.mark.xfail(reason="green after W13: bot_api_get_me behavioral", strict=False)
def test_telegram_checks_bot_api_get_me_mocked() -> None:
    from sevn.browser.recipes import telegram_checks

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"ok": True, "result": {"id": 1, "username": "sevn_bot"}}

    with patch("sevn.browser.recipes.telegram_checks.httpx.get", return_value=_Resp()):
        result = telegram_checks.bot_api_get_me("123:ABC")
    assert result["ok"] is True
    assert result["result"]["username"] == "sevn_bot"


@pytest.mark.xfail(reason="green after W13: telegram_checks operator entrypoint", strict=False)
def test_telegram_checks_has_operator_entrypoint() -> None:
    """Replacement for removed ``telegram-e2e`` must expose a runnable path."""
    from sevn.browser.recipes import telegram_checks

    # Either a CLI main, Make target consumer, or documented runner symbol.
    assert hasattr(telegram_checks, "main") or hasattr(telegram_checks, "run_checks")


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W13: x_ops facade error envelope upgrade", strict=False)
async def test_x_ops_facade_error_path_for_section4_ops() -> None:
    """Upgrade structural callable check: drive envelope/error path for covered ops."""
    from sevn.integrations.social_media import x_ops
    from sevn.integrations.social_media.x_ops_dispatch import FACADE_OPS

    assert FACADE_OPS
    with patch(
        "sevn.integrations.social_media.x_ops_dispatch.resolve_social_medium",
        return_value="browser",
    ):
        result = await x_ops.home_timeline_collect(task={"medium": "browser"}, cfg={}, site="x")
    assert isinstance(result, dict)
    assert "ok" in result
    assert "op" in result
    assert result["op"] == "home_timeline_collect"
