"""Batch E E-Reverify — production mint covers allowlist + budgets; binding enforced.

Reconciliation follow-up after E-Verify gaps:
- E-V1: ``llm_post_auth_failure`` must reject a session token whose ``run_id``
  claim is presented without the matching ``X-Sevn-Run-Id`` header, and must
  reject a token whose ``container_id`` claim is presented without the
  matching ``X-Sevn-Container-Id`` header.
- E-V2: the *production* ``mint_session_token`` must accept ``destination_allowed``,
  ``request_budget``, and ``byte_budget`` parameters and emit a ``limits`` envelope
  that ``session_limits.destination_allowed`` / ``consume_run_budget`` consume.
- E-V3: D51 / C7.2 — the service shared secret alone must not authorize the
  sandbox ``/web/*`` families. This is the moved coverage for the assertion
  that the landed ``test_auth.py`` test cannot express without D40 violation.

These tests live alongside the W18 / W19 / W20 RED suites and exercise the
production code path: ``mint_session_token`` (no test-only builders), the
proxy seam in ``llm_post_auth_failure``, and ``session_limits`` enforcement.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

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
from sevn.proxy.session_limits import (
    BudgetExceeded,
    DestinationNotAllowed,
    consume_run_budget,
    destination_allowed,
    reset_run_budgets_for_tests,
)
from sevn.proxy.settings import ProxySettings

_SERVICE_SECRET = "prod-ready-e-reverify-secret-at-least-32"
_SIGNING_KEY = _SERVICE_SECRET


def _decode_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    assert len(parts) == 3
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    raw = base64.urlsafe_b64decode(padded.encode()).decode()
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    return payload


def _proxy_request(
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


# ---------------------------------------------------------------------------
# E-V2 — production mint emits destination allowlist + per-run budgets
# ---------------------------------------------------------------------------


def test_reverify_v2_mint_with_destination_allowed_emits_limits_envelope() -> None:
    """Producer side: ``mint_session_token(..., destination_allowed=...)`` lives in payload."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-allowlist",
        destination_allowed=["allowed.example", "api.example"],
        expires_at=int(time.time()) + 3600,
    )
    payload = _decode_payload(token)
    limits = payload.get("limits")
    assert isinstance(limits, dict)
    assert limits.get("destinations") == ["allowed.example", "api.example"]


def test_reverify_v2_mint_with_request_and_byte_budgets_emits_limits_envelope() -> None:
    """Producer side: budgets are mirror-typed into the ``limits`` envelope."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-budgets",
        request_budget=3,
        byte_budget=4096,
        expires_at=int(time.time()) + 3600,
    )
    payload = _decode_payload(token)
    limits = payload.get("limits")
    assert isinstance(limits, dict)
    assert limits.get("requests") == 3
    assert limits.get("bytes") == 4096


def test_reverify_v2_mint_without_budgets_omits_limits_envelope() -> None:
    """No speculative defaults: an unconfigured token carries no ``limits`` claim (D49)."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-unbounded",
        expires_at=int(time.time()) + 3600,
    )
    payload = _decode_payload(token)
    assert "limits" not in payload


def test_reverify_v2_session_limits_consume_production_minted_allowlist() -> None:
    """Consumer side: ``destination_allowed`` enforces the production-minted envelope."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-allow-consumer",
        destination_allowed=["allowed.example"],
        expires_at=int(time.time()) + 3600,
    )
    with pytest.raises(DestinationNotAllowed):
        destination_allowed(
            token,
            signing_key=_SIGNING_KEY,
            destination="https://evil.example/",
        )
    assert (
        destination_allowed(
            token,
            signing_key=_SIGNING_KEY,
            destination="https://allowed.example/page",
        )
        is True
    )


def test_reverify_v2_session_limits_consume_production_minted_budgets() -> None:
    """Consumer side: ``consume_run_budget`` enforces the production-minted envelope."""
    reset_run_budgets_for_tests()
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-budget-consumer",
        request_budget=1,
        byte_budget=4096,
        expires_at=int(time.time()) + 3600,
    )
    consume_run_budget(token, signing_key=_SIGNING_KEY, request_bytes=10)
    with pytest.raises(BudgetExceeded):
        consume_run_budget(token, signing_key=_SIGNING_KEY, request_bytes=10)


# ---------------------------------------------------------------------------
# E-V1 — missing binding headers are rejected at the proxy seam
# ---------------------------------------------------------------------------


def test_reverify_v1_validate_rejects_token_when_request_run_id_is_empty() -> None:
    """A token with a ``run_id`` claim is rejected when the request omits the header."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-bound",
        expires_at=int(time.time()) + 3600,
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="",
            container_id="",
        )
        is False
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="run-bound",
            container_id="",
        )
        is True
    )


def test_reverify_v1_validate_rejects_token_when_container_header_is_empty() -> None:
    """A token with a ``container_id`` claim is rejected when the request omits the header."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-ctr",
        container_id="ctr-a",
        expires_at=int(time.time()) + 3600,
    )
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/web/fetch",
            run_id="run-ctr",
            container_id="",
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


def test_reverify_v1_proxy_seam_rejects_session_token_without_run_id_header() -> None:
    """E-V1: the proxy seam must require ``X-Sevn-Run-Id`` for sandbox tokens."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-seam",
        expires_at=int(time.time()) + 3600,
    )
    resp = llm_post_auth_failure(
        _proxy_request(
            path="/web/fetch",
            session_token=token,
            proxy_token=_SERVICE_SECRET,
        ),
        _SERVICE_SECRET,
    )
    assert resp is not None
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_reverify_v1_http_rejects_session_token_without_run_id_header() -> None:
    """HTTP seam version of the E-V1 contract."""
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-http-seam",
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
                # X-Sevn-Run-Id deliberately missing.
            },
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "unauthorized"}


# ---------------------------------------------------------------------------
# E-V3 — D51 / C7.2 coverage moved from the landed test suite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/web/fetch", "/integration"])
def test_reverify_v3_service_secret_rejected_on_sandbox_route_families(path: str) -> None:
    """Service shared secret alone does not authorize sandbox families (D51 / C7.2)."""
    resp = llm_post_auth_failure(
        _proxy_request(path=path, proxy_token=_SERVICE_SECRET),
        _SERVICE_SECRET,
    )
    assert resp is not None
    assert resp.status_code == 401
    assert resp.body == b'{"detail":"unauthorized"}'


def test_reverify_v3_service_secret_still_authorizes_llm_family() -> None:
    """D51 keep-allow side: gateway→proxy ``/llm/*`` still accepts the service secret."""
    assert (
        llm_post_auth_failure(
            _proxy_request(
                path="/llm/openai/chat/completions",
                proxy_token=_SERVICE_SECRET,
            ),
            _SERVICE_SECRET,
        )
        is None
    )


def test_reverify_v3_service_secret_still_authorizes_auth_check_probe() -> None:
    """The ``/web/auth-check`` health probe continues to accept the service secret (C1.4)."""
    assert (
        llm_post_auth_failure(
            _proxy_request(path="/web/auth-check", proxy_token=_SERVICE_SECRET),
            _SERVICE_SECRET,
        )
        is None
    )
