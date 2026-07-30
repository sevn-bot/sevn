"""Telegram menu form re-prompt + cancel (#71 / D19)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.commands.menu_form_handler import MenuFormHandler
from sevn.gateway.dispatcher.dispatcher_state import insert_dispatcher_state
from sevn.storage.migrate import apply_migrations


def _advertises_cancel(text: str) -> bool:
    low = text.lower()
    return "cancel" in low or "abort" in low or "✗" in text


def _chat_msg(*, text: str = "x", chat_id: int = 1) -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        user_id="owner",
        text=text,
        metadata={"chat_id": chat_id, "owner": True},
    )


@dataclass
class _FormHarness:
    handler: MenuFormHandler
    conn: sqlite3.Connection
    sent: list[str]

    async def start(self, target: str) -> str:
        await self.handler._start_form(_chat_msg(), target=target)
        row = self.conn.execute(
            "SELECT token FROM dispatcher_state WHERE consumed = 0 ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        assert row is not None
        return str(row[0])

    def token_consumed(self, token: str) -> bool:
        row = self.conn.execute(
            "SELECT consumed FROM dispatcher_state WHERE token = ?",
            (token,),
        ).fetchone()
        return row is not None and int(row[0]) == 1


@pytest.fixture
def form_harness(tmp_path: Path) -> _FormHarness:
    cfg = WorkspaceConfig.minimal()
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(json.dumps(cfg.model_dump(mode="json")), encoding="utf-8")
    router = MagicMock()
    router._resolve_owner_flag.return_value = True
    router._content_root = tmp_path
    router._workspace = cfg
    adapter = MagicMock()
    adapter.send = AsyncMock()
    router._adapters = {"telegram": adapter}
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    handler = MenuFormHandler(
        workspace=cfg,
        router=router,
        conn=conn,
        content_root=tmp_path,
        sevn_json_path=sevn_json,
    )
    sent: list[str] = []

    async def _capture_chat(_msg: object, text: str, **_kw: object) -> None:
        sent.append(text)

    handler._send_chat = _capture_chat  # type: ignore[method-assign,assignment]
    handler._answer_callback = AsyncMock()  # type: ignore[method-assign,assignment]
    handler._consume_active_forms = lambda _msg: None  # type: ignore[method-assign,assignment]
    return _FormHarness(handler=handler, conn=conn, sent=sent)


@pytest.mark.asyncio
async def test_tunnel_setup_first_prompt_advertises_cancel(form_harness: _FormHarness) -> None:
    """Discoverability: value-required prompts must mention cancel on the first ask."""
    await form_harness.start("tunnel:setup")
    assert form_harness.sent
    assert _advertises_cancel(form_harness.sent[-1])
    assert "tunnel mode" in form_harness.sent[-1].lower()


@pytest.mark.asyncio
async def test_tunnel_setup_invalid_mode_reprompts_with_cancel(form_harness: _FormHarness) -> None:
    token = await form_harness.start("tunnel:setup")
    form_harness.sent.clear()
    await form_harness.handler._advance_tunnel_setup_form(
        _chat_msg(text="not-a-mode"),
        token=token,
        step="mode",
        text="not-a-mode",
        payload={"target": "tunnel:setup", "step": "mode"},
    )
    assert len(form_harness.sent) >= 2
    assert any("mode must be" in line.lower() for line in form_harness.sent)
    assert any(_advertises_cancel(line) for line in form_harness.sent)
    assert any("tunnel mode" in line.lower() for line in form_harness.sent)
    assert not form_harness.token_consumed(token)


@pytest.mark.asyncio
async def test_tunnel_setup_cancel_clears_form_token(form_harness: _FormHarness) -> None:
    """Generic cancel vocabulary already works — must keep clearing the token."""
    token = await form_harness.start("tunnel:setup")
    await form_harness.handler._advance_form(_chat_msg(text="cancel"))
    assert form_harness.token_consumed(token)
    assert any("cancelled" in line.lower() for line in form_harness.sent)


@pytest.mark.asyncio
async def test_tunnel_setup_quick_reaches_config_writer_as_cloudflare_quick(
    form_harness: _FormHarness,
) -> None:
    """W1.4: ``quick`` must normalize to ``cloudflare_quick`` before config write."""
    token = await form_harness.start("tunnel:setup")
    captured: dict[str, Any] = {}

    def _capture_build(*, mode: str, **kwargs: object) -> dict[str, object]:
        captured["mode"] = mode
        _ = kwargs
        return {"infrastructure.tunnel.mode": mode}

    with (
        patch(
            "sevn.cli.gateway_token_store.GatewayTokenBootstrap",
            return_value=MagicMock(),
        ),
        patch(
            "sevn.cli.commands.tunnel_cmd._build_config_fields",
            side_effect=_capture_build,
        ),
        patch(
            "sevn.cli.tunnel_setup_store.apply_tunnel_setup_local",
            new=AsyncMock(),
        ),
    ):
        await form_harness.handler._advance_tunnel_setup_form(
            _chat_msg(text="quick"),
            token=token,
            step="mode",
            text="quick",
            payload={"target": "tunnel:setup", "step": "mode"},
        )
    assert captured.get("mode") == "cloudflare_quick"


@dataclass(frozen=True)
class _InvalidFormCase:
    target: str
    step: str
    invalid_text: str
    advance: Callable[..., Awaitable[None]]
    error_fragment: str


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _InvalidFormCase(
                target="logs_grep",
                step="pattern",
                invalid_text="",
                advance=lambda h, msg, token, payload: h._advance_logs_grep(
                    msg, token=token, step="pattern", text="", payload=payload
                ),
                error_fragment="pattern cannot be empty",
            ),
            id="logs_grep-empty",
        ),
        pytest.param(
            _InvalidFormCase(
                target="config:set",
                step="path",
                invalid_text="",
                advance=lambda h, msg, token, payload: h._advance_config_set_form(
                    msg, token=token, step="path", text="", payload=payload
                ),
                error_fragment="dot path cannot be empty",
            ),
            id="config_set-empty-path",
        ),
        pytest.param(
            _InvalidFormCase(
                target="memory:backfill",
                step="window",
                invalid_text="not-a-window",
                advance=lambda h, msg, token, payload: h._advance_memory_backfill(
                    msg, token=token, step="window", text="not-a-window", payload=payload
                ),
                error_fragment="send two dates",
            ),
            id="memory_backfill-invalid",
        ),
        pytest.param(
            _InvalidFormCase(
                target="pairing:approve",
                step="approve",
                invalid_text="only-one-token",
                advance=lambda h, msg, token, payload: h._advance_pairing_approve_form(
                    msg,
                    token=token,
                    step="approve",
                    text="only-one-token",
                    payload=payload,
                ),
                error_fragment="send channel and code",
            ),
            id="pairing_approve-invalid",
        ),
    ],
)
async def test_invalid_form_input_reprompts_with_cancel(
    form_harness: _FormHarness,
    case: _InvalidFormCase,
) -> None:
    token = f"ds:case-{case.target}"
    payload = {"target": case.target, "step": case.step}
    insert_dispatcher_state(
        form_harness.conn,
        token=token,
        kind="form",
        user_id=1,
        chat_id=1,
        topic_id=None,
        payload_json=json.dumps({"v": 1, **payload}, separators=(",", ":")),
        ttl_seconds=3600,
    )
    form_harness.sent.clear()
    msg = _chat_msg(text=case.invalid_text)
    await case.advance(form_harness.handler, msg, token, payload)
    assert any(case.error_fragment in line.lower() for line in form_harness.sent)
    assert any(_advertises_cancel(line) for line in form_harness.sent)
    assert not form_harness.token_consumed(token)
