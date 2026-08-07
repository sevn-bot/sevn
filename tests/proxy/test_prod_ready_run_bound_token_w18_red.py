"""Batch E W18 RED — run-bound session tokens + differentiated authority (C7.1, C7.2, D51).

Scoped to the *remainder* of C7.1: ``run_id`` is already embedded in the mint payload
(W0 correction @ ``2c1c6831``); this suite pins **enforcement** across runs, **container
binding**, and **service-secret rejection** on sandbox route families. Landed signature /
``exp`` / route-family scope rejects stay green here (W18.7) — do not re-assert them as
failing.

Reconciliation: W18.1-W18.3 xfails removed after W19 (`8a86aa95`); W18.7 stays green.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from starlette.requests import Request

from sevn.proxy.app import create_app
from sevn.proxy.auth import (
    SESSION_SCOPE_SANDBOX,
    llm_post_auth_failure,
    mint_session_token,
    validate_session_token,
)
from sevn.proxy.settings import ProxySettings
from sevn.security.sandbox_runtime import build_sandbox_child_env

_SERVICE_SECRET = "prod-ready-e-service-secret-at-least-32"
_SIGNING_KEY = _SERVICE_SECRET


def _request(
    *,
    method: str = "POST",
    path: str = "/web/fetch",
    proxy_token: str | None = None,
    session_token: str | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if proxy_token is not None:
        headers.append((b"x-sevn-proxy-token", proxy_token.encode()))
    if session_token is not None:
        headers.append((b"x-sevn-session-token", session_token.encode()))
    if extra_headers:
        headers.extend(extra_headers)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def _decode_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    assert len(parts) == 3
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    raw = base64.urlsafe_b64decode(padded.encode()).decode()
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def _mint_bound_token(
    *,
    signing_key: str,
    scope: str,
    run_id: str,
    container_id: str,
    expires_at: int | None = None,
) -> str:
    """Future mint shape (W19): payload carries ``run_id`` + ``container_id``."""
    exp = expires_at if expires_at is not None else int(time.time()) + 3600
    payload = {
        "scope": scope,
        "exp": exp,
        "run_id": run_id,
        "container_id": container_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"v1.{body}.{sig}"


# ---------------------------------------------------------------------------
# W18.7 — landed contracts (green on batch base; unmodified semantics)
# ---------------------------------------------------------------------------


def test_w18_7_mint_embeds_run_id_claim_already_landed() -> None:
    """W0 correction: ``run_id`` is already in the mint payload — not a W19 introduce."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-already-present",
        expires_at=int(time.time()) + 3600,
    )
    payload = _decode_payload(token)
    assert payload.get("run_id") == "run-already-present"


def test_w18_7_session_token_rejects_forged_signature() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-sig",
        expires_at=int(time.time()) + 3600,
    )
    forged = token[:-4] + "dead"
    assert validate_session_token(forged, signing_key=_SIGNING_KEY, path="/web/fetch") is False


def test_w18_7_session_token_rejects_expired() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-exp",
        expires_at=int(time.time()) - 60,
    )
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is False


def test_w18_7_session_token_rejects_wrong_route_family_scope() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-scope",
        expires_at=int(time.time()) + 3600,
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/llm/openai/chat/completions",
        )
        is False
    )
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is True


def test_w18_7_build_sandbox_child_env_excludes_service_secret() -> None:
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:8787",
        session_token="per-run-session-token",
        workspace_mount_path="/workspace",
    )
    assert "SEVN_PROXY_SHARED_SECRET" not in env
    assert _SERVICE_SECRET not in env.values()
    assert env.get("SEVN_SESSION_TOKEN") == "per-run-session-token"


# ---------------------------------------------------------------------------
# W18.1 — run_id claim enforcement across runs (C7.1 remainder; green after W19)
# ---------------------------------------------------------------------------


def test_w18_1_validate_rejects_token_when_request_run_id_mismatches() -> None:
    """Token minted for run A must not authorize a request attributed to run B."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-a",
        expires_at=int(time.time()) + 3600,
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="run-b",
        )
        is False
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="run-a",
        )
        is True
    )


@pytest.mark.anyio
async def test_w18_1_http_rejects_session_token_for_foreign_run() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-a",
        expires_at=int(time.time()) + 3600,
    )
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={
                "X-Sevn-Session-Token": token,
                "X-Sevn-Run-Id": "run-b",
            },
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


# ---------------------------------------------------------------------------
# W18.2 — spawning-container binding (C7.1 remainder; green after W19)
# ---------------------------------------------------------------------------


def test_w18_2_mint_embeds_container_id_claim() -> None:
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-ctr",
        container_id="ctr-spawn-1",
        expires_at=int(time.time()) + 3600,
    )
    payload = _decode_payload(token)
    assert payload.get("container_id") == "ctr-spawn-1"


def test_w18_2_validate_rejects_token_from_different_container() -> None:
    token = _mint_bound_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-ctr",
        container_id="ctr-a",
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="run-ctr",
            container_id="ctr-b",
        )
        is False
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="run-ctr",
            container_id="ctr-a",
        )
        is True
    )


@pytest.mark.anyio
async def test_w18_2_http_rejects_replay_from_different_container() -> None:
    token = _mint_bound_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-ctr",
        container_id="ctr-a",
    )
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={
                "X-Sevn-Session-Token": token,
                "X-Sevn-Run-Id": "run-ctr",
                "X-Sevn-Container-Id": "ctr-b",
            },
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


# ---------------------------------------------------------------------------
# E-THERMOS-2/3 — container_id non-str token claim must return False, not TypeError
# ---------------------------------------------------------------------------


def test_container_id_int_zero_rejected_returns_false_not_typeerror() -> None:
    """A token whose ``container_id`` claim is int(0) must be rejected as False.

    Regression: F-2/F-3 — without the isinstance guard, ``hmac.compare_digest(0, "0")``
    raises ``TypeError`` and propagates as a 500 from Starlette. Returning ``False``
    keeps the request on the 401 path.
    """
    exp = int(time.time()) + 3600
    payload = {
        "scope": SESSION_SCOPE_SANDBOX,
        "exp": exp,
        "run_id": "run-zero-ctr",
        "container_id": 0,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(_SIGNING_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    token = f"v1.{body}.{sig}"

    result = validate_session_token(
        token,
        signing_key=_SIGNING_KEY,
        path="/web/fetch",
        run_id="run-zero-ctr",
        container_id="0",
    )
    assert result is False


# ---------------------------------------------------------------------------
# W18.3 — C7.2 / D51: service secret rejected on sandbox families
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/web/fetch", "/integration"],
)
def test_w18_3_service_secret_rejected_on_sandbox_route_families(path: str) -> None:
    """Sandbox-originated families require a session token — service secret alone is 401."""
    resp = llm_post_auth_failure(
        _request(path=path, proxy_token=_SERVICE_SECRET),
        _SERVICE_SECRET,
    )
    assert resp is not None
    assert resp.status_code == 401
    assert resp.body == b'{"detail":"unauthorized"}'


def test_w18_3_service_secret_still_accepted_on_gateway_llm_family() -> None:
    """D51 keep-allow side — already true on the batch base; must stay green through W19."""
    assert (
        llm_post_auth_failure(
            _request(path="/llm/openai/chat/completions", proxy_token=_SERVICE_SECRET),
            _SERVICE_SECRET,
        )
        is None
    )


@pytest.mark.anyio
async def test_w18_3_http_service_secret_rejected_on_web_fetch() -> None:
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={"X-Sevn-Proxy-Token": _SERVICE_SECRET},
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


@pytest.mark.anyio
async def test_w18_3_http_service_secret_accepted_on_llm_route() -> None:
    """D51 keep-allow side — green on batch base; W19 must not regress gateway→proxy LLM."""
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={"model": "x"},
            headers={"X-Sevn-Proxy-Token": _SERVICE_SECRET},
        )
    # Proxy auth passed; upstream may still 401 on the placeholder API key.
    assert resp.json().get("detail") != "unauthorized"
