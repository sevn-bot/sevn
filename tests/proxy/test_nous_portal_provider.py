"""Nous Portal provider config and proxy smoke tests (#153 W17 / D15)."""

from __future__ import annotations

import httpx
import pytest

from sevn.agent.providers import resolve_model
from sevn.agent.triager.run import resolve_triager_transport_name
from sevn.config.defaults import (
    DEFAULT_NOUS_INFERENCE_BASE_URL,
    NOUS_PORTAL_DEEPSEEK_V4_FLASH_MODEL_ID,
)
from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.config.provider_registry import resolve_provider_binding, resolve_provider_for_model_id
from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.app import create_app
from sevn.proxy.credentials import (
    ProviderCredentialEntry,
    ProviderCredentials,
    credential_unresolved_detail,
    resolve_request_credential,
)
from sevn.proxy.settings import ProxySettings

_NOUS_MODEL = NOUS_PORTAL_DEEPSEEK_V4_FLASH_MODEL_ID
_NOUS_BASE = DEFAULT_NOUS_INFERENCE_BASE_URL


def _nous_workspace(*, with_key: bool = True) -> WorkspaceConfig:
    """Minimal workspace using DeepSeek V4 Flash via Nous Portal."""
    nous_block: dict[str, str] = {"base_url": _NOUS_BASE}
    if with_key:
        nous_block["api_key"] = "${SECRET:SEVN_SECRET_NOUS}"
    return WorkspaceConfig.minimal(
        providers={
            "tier_default": {"triager": _NOUS_MODEL, "B": _NOUS_MODEL},
            "nous": nous_block,
            "models": {_NOUS_MODEL: {"provider": "nous"}},
        },
    )


def test_nous_portal_constants_match_documented_values() -> None:
    """W17.1: base URL and model id match Nous/Hermes Portal docs (no guessing)."""
    assert _NOUS_BASE == "https://inference-api.nousresearch.com/v1"
    assert _NOUS_MODEL == "deepseek/deepseek-v4-flash"


def test_deepseek_v4_flash_routes_to_nous_provider_with_override() -> None:
    """W17.3: providers.models override binds deepseek/* slug to nous registry."""
    cfg = _nous_workspace()
    assert resolve_provider_for_model_id(cfg, _NOUS_MODEL) == "nous"
    binding = resolve_provider_binding(cfg, "nous")
    assert binding.base_url == _NOUS_BASE
    assert binding.api_key_ref == "${SECRET:SEVN_SECRET_NOUS}"


def test_tier_slot_and_triager_transport_resolve_for_nous_model() -> None:
    """W17.4: assigned tier slots and triager transport resolve without error."""
    cfg = _nous_workspace()
    assert resolve_model_slot(cfg, ModelSlot.triager) == _NOUS_MODEL
    assert resolve_model_slot(cfg, ModelSlot.tier_b) == _NOUS_MODEL
    providers = cfg.providers if isinstance(cfg.providers, dict) else {}
    assert resolve_triager_transport_name(providers, _NOUS_MODEL) == "chat_completions"
    _, transport = resolve_model(model_id=_NOUS_MODEL, transport_name="chat_completions")
    assert transport.name == "chat_completions"


def test_resolve_request_credential_uses_nous_base_url() -> None:
    """W17.3: proxy credential resolution picks Nous inference base URL."""
    cfg = _nous_workspace()
    app_state = type(
        "S",
        (),
        {
            "settings": ProxySettings(openai_api_key="sk-env"),
            "provider_credentials": ProviderCredentials(
                by_name={
                    "nous": ProviderCredentialEntry(
                        api_key="nous-jwt-test",
                        base_url=_NOUS_BASE,
                        openai_base_url=_NOUS_BASE,
                    ),
                },
            ),
        },
    )()
    key, base = resolve_request_credential(
        cfg,
        app_state,
        _NOUS_MODEL,
        "/llm/openai/chat/completions",
    )
    assert key == "nous-jwt-test"
    assert base == _NOUS_BASE


@pytest.mark.anyio
async def test_nous_chat_completions_round_trip_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """W17.5: chat/completions round-trip forwards bearer + Nous base URL."""
    captured: dict[str, object] = {}

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        captured["url"] = kwargs["url"]
        captured["headers"] = kwargs["headers"]
        captured["body"] = kwargs["body"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-nous",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    cfg = _nous_workspace()
    app = create_app(
        settings=ProxySettings(openai_api_key="sk-env"),
        workspace_config=cfg,
    )
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "nous": ProviderCredentialEntry(
                api_key="nous-jwt-test",
                base_url=_NOUS_BASE,
                openai_base_url=_NOUS_BASE,
            ),
        },
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": _NOUS_MODEL, "messages": [{"role": "user", "content": "ping"}]},
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == "chatcmpl-nous"
    assert captured["url"] == f"{_NOUS_BASE}/chat/completions"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers.get("authorization") == "Bearer nous-jwt-test"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == _NOUS_MODEL


@pytest.mark.anyio
async def test_nous_bad_key_returns_upstream_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """W17.5: invalid bearer surfaces structured upstream 401 (not masked as 503)."""

    async def capture_post_json(**kwargs: object) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "Invalid API key", "type": "invalid_request_error"}},
        )

    monkeypatch.setattr("sevn.proxy.app.post_json", capture_post_json)
    cfg = _nous_workspace()
    app = create_app(
        settings=ProxySettings(openai_api_key="sk-env"),
        workspace_config=cfg,
    )
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "nous": ProviderCredentialEntry(
                api_key="bad-key",
                base_url=_NOUS_BASE,
                openai_base_url=_NOUS_BASE,
            ),
        },
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": _NOUS_MODEL, "messages": []},
        )
    assert resp.status_code == 401
    payload = resp.json()
    assert payload["error"]["message"] == "Invalid API key"


@pytest.mark.anyio
async def test_nous_missing_credential_returns_structured_503() -> None:
    """W17.5: unresolved nous secret yields operator-facing 503 detail."""
    cfg = _nous_workspace(with_key=True)
    app = create_app(
        settings=ProxySettings(openai_api_key=None, anthropic_api_key=None),
        workspace_config=cfg,
    )
    app.state.provider_credentials = ProviderCredentials(
        by_name={
            "nous": ProviderCredentialEntry(
                api_key=None,
                base_url=_NOUS_BASE,
                openai_base_url=_NOUS_BASE,
            ),
        },
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": _NOUS_MODEL, "messages": []},
        )
    assert resp.status_code == 503
    assert resp.json()["detail"] == credential_unresolved_detail("nous")
