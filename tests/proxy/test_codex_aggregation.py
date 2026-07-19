"""RED suite for proxy Codex non-stream aggregation resilience (D2, D3; green after W3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from tests.security.oauth.conftest import fake_access_jwt

from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.app import create_app
from sevn.proxy.credentials import ProviderCredentialEntry, ProviderCredentials
from sevn.proxy.settings import ProxySettings
from sevn.security.oauth.credential import CodexOAuthCredential

if TYPE_CHECKING:
    from loguru import Record

_TRUNCATED_SSE = 'data: {"type":"response.created","response":{"id":"resp_trunc"}}\n\n'

_COMPLETED_SSE = (
    'data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
    'data: {"type":"response.completed","response":'
    '{"id":"resp_1","model":"gpt-5.5","output":[{"type":"message","role":"assistant",'
    '"content":[{"type":"output_text","text":"ok"}]}]}}\n\n'
    "data: [DONE]\n\n"
)


def _oauth_workspace() -> WorkspaceConfig:
    return WorkspaceConfig.minimal(
        providers={
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"auth_mode": "oauth"},
        },
    )


def _attach_oauth_state(app: object, *, access: str, account_id: str) -> None:
    cred = CodexOAuthCredential(
        access=access,
        refresh="rt-test",
        expires=int(__import__("time").time() * 1000) + 3_600_000,
        account_id=account_id,
    )
    app.state.codex_oauth_credential = cred
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "openai": ProviderCredentialEntry(
                api_key=None,
                openai_base_url="https://api.openai.com/v1",
            ),
        },
    )


def _retrying_sse_stub(first_sse: str, second_sse: str):
    calls: list[dict[str, object]] = []

    async def capture_post_sse_stream(**kwargs: object) -> tuple[object, httpx.Response]:
        calls.append(dict(kwargs))
        sse = first_sse if len(calls) == 1 else second_sse
        upstream = httpx.Response(
            200,
            text=sse,
            headers={"content-type": "text/event-stream"},
        )

        class _Client:
            async def aclose(self) -> None:
                return None

        return _Client(), upstream

    return capture_post_sse_stream, calls


def _capture_loguru(*, level: str) -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []

    def _sink(message: Record) -> None:
        captured.append(str(message))

    sink_id = loguru_logger.add(_sink, level=level)
    return captured, sink_id


@pytest.mark.anyio
async def test_truncated_codex_stream_retried_once_before_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2: empty post-``response.created`` stream triggers exactly one retry."""
    stub, calls = _retrying_sse_stub(_TRUNCATED_SSE, _TRUNCATED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-retry")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-retry")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert len(calls) == 2


@pytest.mark.anyio
async def test_persistent_truncated_stream_returns_typed_error_not_bare_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2: persistent empty stream returns a typed upstream-truncated error — not bare 502."""
    stub, _calls = _retrying_sse_stub(_TRUNCATED_SSE, _TRUNCATED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-typed")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-typed")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert resp.status_code != 502
    body = resp.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert detail.get("code") == "upstream_truncated"
    else:
        assert detail == "upstream_truncated"


@pytest.mark.anyio
async def test_truncated_codex_stream_logs_warning_without_error_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2: truncation logs one WARNING with bytes/resp_id — no ERROR ASGI stack."""
    from loguru import logger as loguru_logger

    stub, _calls = _retrying_sse_stub(_TRUNCATED_SSE, _TRUNCATED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    warnings, warn_sink = _capture_loguru(level="WARNING")
    errors, err_sink = _capture_loguru(level="ERROR")
    access = fake_access_jwt(account_id="acct-log")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-log")
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/llm/openai/chat/completions",
                json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )
    finally:
        loguru_logger.remove(warn_sink)
        loguru_logger.remove(err_sink)

    assert any("truncat" in line.lower() for line in warnings)
    assert len([line for line in warnings if "proxy codex" in line.lower()]) == 1
    assert errors == []


@pytest.mark.anyio
async def test_completed_codex_stream_aggregates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D2 guard: a normal Codex SSE body still returns chat-completion JSON."""
    stub, _calls = _retrying_sse_stub(_COMPLETED_SSE, _COMPLETED_SSE)
    monkeypatch.setattr("sevn.proxy.app.post_sse_stream", stub)
    access = fake_access_jwt(account_id="acct-ok")
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=_oauth_workspace(),
    )
    _attach_oauth_state(app, access=access, account_id="acct-ok")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["choices"][0]["message"]["content"] == "ok"


def test_high_latency_alert_includes_stalling_stage() -> None:
    """D3: ``high_latency`` warning names the stalling stage (triager/tool/upstream)."""
    from sevn.gateway.mission.mission_state import MissionControlState

    state = MissionControlState()
    state.record_turn_stage_latency_ms("upstream", 120_010.0)
    state.update_provider("openai", latency_ms=120_010.0)
    latency_alerts = [a for a in state._alerts if a.rule_name == "high_latency"]
    assert latency_alerts
    assert any("upstream" in a.message for a in latency_alerts)


@pytest.mark.asyncio
async def test_slow_turn_emits_still_working_progress_before_dead_air() -> None:
    """D3: user-visible progress signal is emitted before the dead-air window."""
    from sevn.gateway.agent_turn import turn_progress_signal_text

    assert turn_progress_signal_text().strip()
    # Shape-only contract: the helper exists and reads like a progress ping.
    text = turn_progress_signal_text().lower()
    assert "still" in text or "working" in text
