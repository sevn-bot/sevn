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
- E-V3 followup: tests deleted from landed C1.1 suites (``test_auth.py`` and
  ``test_post_audit_proxy_auth_w4_red.py``) because they pinned pre-W19/W20
  behavior the new implementation inverts — the post-W19/W20 assertion
  lives here.

These tests live alongside the W18 / W19 / W20 RED suites and exercise the
production code path: ``mint_session_token`` (no test-only builders), the
proxy seam in ``llm_post_auth_failure``, and ``session_limits`` enforcement.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
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


def _binding_signature(*, container_id: str, run_id: str) -> str:
    """Compute the PoP binding signature used by the proxy guard (PR #245 finding 5)."""
    canonical = f"container_id={container_id}\nrun_id={run_id}".encode()
    return hmac.new(_SERVICE_SECRET.encode(), canonical, hashlib.sha256).hexdigest()


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


# ---------------------------------------------------------------------------
# E-V3/E-V1 followup — coverage of obsolete landed tests removed under D40
# ---------------------------------------------------------------------------
#
# The wave-orchestrator landed the C1.1 regression suites (``test_auth.py``,
# ``test_post_audit_proxy_auth_w4_red.py``) before W19/W20 inverted their
# expectations. Restoring them unmodified (D40) makes their assertions
# contradict the post-implementation proxy behavior. The same contracts are
# restated here against the production mint path so a wave-author or reviewer
# who inspects this file directly sees the post-W19/W20 contract.
#
# These tests do NOT exercise the ``mint_session_token`` internals — that is
# already covered by ``test_reverify_v1_*`` and ``test_reverify_v2_*`` above —
# but they do mirror the deleted tests' request shapes (POST ``/web/fetch``,
# concurrent same-credential gather) so the regression intent is preserved.


def test_reverify_v3_service_secret_rejected_on_post_web_route() -> None:
    """E-V3 / C7.2: service secret alone does not authorize POST ``/web/fetch`` (D51).

    Mirror of the deleted ``test_release_audit_ssrf_w1_red::
    test_proxy_auth_accepts_post_with_correct_token_regression`` and the
    pre-W19/W20 ``test_auth.py::test_llm_post_auth_failure_guarded_web_prefix``
    form — both pinned the obsolete allow-secret assertion.
    """
    resp = llm_post_auth_failure(
        _proxy_request(path="/web/fetch", proxy_token=_SERVICE_SECRET),
        _SERVICE_SECRET,
    )
    assert resp is not None
    assert resp.status_code == 401
    assert resp.body == b'{"detail":"unauthorized"}'


@pytest.mark.anyio
async def test_reverify_v1_run_id_required_for_sandbox_web_route() -> None:
    """E-V1: a sandbox session token missing ``X-Sevn-Run-Id`` is rejected.

    Mirror of the deleted ``test_post_audit_proxy_auth_w4_red::
    test_valid_sandbox_session_token_accepted_on_web_route`` — the landed
    form pinned the pre-W19/W20 accept-without-binding behavior.
    """
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-bind-required",
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
            headers={"X-Sevn-Session-Token": token},
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_reverify_v1_run_id_binding_matches_when_present() -> None:
    """E-V1: a sandbox session token + matching ``X-Sevn-Run-Id`` is accepted.

    Companion of the deleted ``test_valid_sandbox_session_token_accepted_on_web_route``
    — specifies the post-W19/W20 accept path so a regression that loosens
    the binding requirement also breaks this test.
    """
    run_id = "run-binding-matches"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
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
    binding_sig = _binding_signature(container_id="", run_id=run_id)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={
                "X-Sevn-Session-Token": token,
                "X-Sevn-Run-Id": run_id,
                "X-Sevn-Binding-Signature": binding_sig,
            },
        )
    assert resp.status_code != 401
    assert resp.json().get("detail") != "unauthorized"


@pytest.mark.anyio
async def test_reverify_v1_concurrent_run_id_bound_requests_consistent() -> None:
    """E-V1 / P4a: concurrent same-credential requests with binding agree (no race bypass).

    Mirror of the deleted ``test_post_audit_proxy_auth_w4_red::
    test_concurrent_same_session_token_requests_consistent`` — the landed
    form issued two POSTs with the same token and no binding header and
    asserted both replies were not 401. The new auth seam rejects tokens
    without the binding header, so the symmetric post-W19/W20 assertion is
    that *both* concurrent same-token replies are consistent and not 401
    when the binding header is supplied.
    """
    import asyncio

    run_id = "run-concurrent-binding"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
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
    binding_sig = _binding_signature(container_id="", run_id=run_id)

    async def _fetch() -> int:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/web/fetch",
                json={"url": "https://example.com/"},
                headers={
                    "X-Sevn-Session-Token": token,
                    "X-Sevn-Run-Id": run_id,
                    "X-Sevn-Binding-Signature": binding_sig,
                },
            )
            return resp.status_code

    codes = await asyncio.gather(_fetch(), _fetch())
    assert codes[0] == codes[1]
    assert codes[0] != 401


# ---------------------------------------------------------------------------
# E-PoP — Binding-headers PoP signature (PR #245 Codex finding 5)
# ---------------------------------------------------------------------------


def _request_with_binding(
    *,
    token: str,
    run_id: str,
    container_id: str,
    signing_key: str,
    include_sig: bool = True,
    wrong_sig: bool = False,
    path: str = "/web/fetch",
) -> Request:
    """Synthesize an ASGI ``Request`` carrying the PoP binding headers.
    Local helper (D40-safe: does not live in ``test_auth.py``).
    """
    binding_sig = ""
    if include_sig:
        canonical = f"container_id={container_id}\nrun_id={run_id}".encode()
        binding_sig = hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()
        if wrong_sig:
            binding_sig = "deadbeef" * 8
    headers: list[tuple[bytes, bytes]] = [
        (b"x-sevn-proxy-token", b"ignored"),
        (b"x-sevn-session-token", token.encode()),
        (b"x-sevn-run-id", run_id.encode()),
        (b"x-sevn-container-id", container_id.encode()),
    ]
    if include_sig:
        headers.append((b"x-sevn-binding-signature", binding_sig.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_e_pop_verify_binding_signature_accepts_matching_signature() -> None:
    """A correctly keyed binding signature is admitted by the verifier."""
    from sevn.proxy.auth import _verify_binding_signature

    run_id = "run-pop"
    container_id = "ctr-pop"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
        container_id=container_id,
        expires_at=int(time.time()) + 3600,
    )
    req = _request_with_binding(
        token=token,
        run_id=run_id,
        container_id=container_id,
        signing_key=_SIGNING_KEY,
    )
    assert (
        _verify_binding_signature(
            request=req, signing_key=_SIGNING_KEY, container_id=container_id, run_id=run_id
        )
        is True
    )


def test_e_pop_verify_binding_signature_rejects_missing_header() -> None:
    """An absent binding signature is rejected (fail-closed)."""
    from sevn.proxy.auth import _verify_binding_signature

    run_id = "run-pop"
    container_id = "ctr-pop"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
        container_id=container_id,
        expires_at=int(time.time()) + 3600,
    )
    req = _request_with_binding(
        token=token,
        run_id=run_id,
        container_id=container_id,
        signing_key=_SIGNING_KEY,
        include_sig=False,
    )
    assert (
        _verify_binding_signature(
            request=req, signing_key=_SIGNING_KEY, container_id=container_id, run_id=run_id
        )
        is False
    )


def test_e_pop_verify_binding_signature_rejects_mismatched_signature() -> None:
    """A signature keyed by a different secret is rejected."""
    from sevn.proxy.auth import _verify_binding_signature

    run_id = "run-pop"
    container_id = "ctr-pop"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
        container_id=container_id,
        expires_at=int(time.time()) + 3600,
    )
    req = _request_with_binding(
        token=token,
        run_id=run_id,
        container_id=container_id,
        signing_key="wrong-signing-key-32-chars!!",
    )
    assert (
        _verify_binding_signature(
            request=req, signing_key=_SIGNING_KEY, container_id=container_id, run_id=run_id
        )
        is False
    )


def test_e_pop_llm_post_auth_failure_rejects_session_token_without_binding_signature() -> None:
    """Session tokens without a PoP binding signature are rejected at the guard."""
    run_id = "run-pop"
    container_id = "ctr-pop"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
        container_id=container_id,
        expires_at=int(time.time()) + 3600,
    )
    req = _request_with_binding(
        token=token,
        run_id=run_id,
        container_id=container_id,
        signing_key=_SIGNING_KEY,
        include_sig=False,
    )
    resp = llm_post_auth_failure(req, _SIGNING_KEY, allow_unauthenticated=False)
    assert resp is not None
    assert resp.status_code == 401


def test_e_pop_llm_post_auth_failure_accepts_session_token_with_binding_signature() -> None:
    """A PoP-signed request is admitted."""
    run_id = "run-pop"
    container_id = "ctr-pop"
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
        container_id=container_id,
        expires_at=int(time.time()) + 3600,
    )
    req = _request_with_binding(
        token=token, run_id=run_id, container_id=container_id, signing_key=_SIGNING_KEY
    )
    assert llm_post_auth_failure(req, _SIGNING_KEY, allow_unauthenticated=False) is None
