"""MergeCraft review 4885607539 — Batch E W18 RED follow-ups (C7.3).

Addresses the three inline comments from ``/pull/245#issuecomment-5220727143``:

1. **Byte budget must count response/egress bytes, not request body alone**
   (``app.py`` and ``session_limits.py``). The reviewer asked for either
   a response-byte measurement or honest "request-body only" schema copy.
   This suite pins the former: ``consume_response_bytes`` charges the
   ``text`` payload ``web_fetch_json`` returns, and ``web_fetch`` returns
   ``429`` when the budget is exhausted on the egress side.
2. **Bound / prune ``_BUDGETS``** (``session_limits.py``). ``exp``-based
   lazy eviction keeps the dict from growing without bound for the proxy's
   lifetime.
3. **Per-call random ``run_id``** (``tools/web.py``). The
   ``build_egress_web_headers`` fallback path must not pin every gateway
   egress call to a single constant run id.

These tests are RED-targeted at the mergecraft findings and cover only the
three contracts under review (no broader scope).

Examples:
    >>> from tests.proxy.test_prod_ready_egress_response_bytes_mergecraft import (
    ...     _SIGNING_KEY,
    ... )
    >>> _SIGNING_KEY.startswith("prod-ready-e-mc")
    True
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

from sevn.proxy import session_limits
from sevn.proxy.app import create_app
from sevn.proxy.auth import mint_session_token
from sevn.proxy.settings import ProxySettings

_SERVICE_SECRET = "prod-ready-e-mc-secret-at-least-32-chars"
_SIGNING_KEY = _SERVICE_SECRET
_SANDBOX_SCOPE = "sandbox"


def _mint_budgeted_token(
    *,
    signing_key: str,
    run_id: str,
    max_requests: int | None = None,
    max_bytes: int | None = None,
    container_id: str = "ctr-mc-1",
    expires_at: int | None = None,
) -> str:
    """Production-shaped token (mint_session_token) with budgets in ``limits`` envelope."""
    return mint_session_token(
        signing_key=signing_key,
        scope=_SANDBOX_SCOPE,
        run_id=run_id,
        container_id=container_id,
        request_budget=max_requests,
        byte_budget=max_bytes,
        expires_at=expires_at if expires_at is not None else int(time.time()) + 3600,
    )


def _proxy_app() -> Any:
    return create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )


# ---------------------------------------------------------------------------
# Finding 1 — byte budget measures response bytes, not request body alone
# ---------------------------------------------------------------------------


def test_consume_response_bytes_charges_against_byte_budget() -> None:
    """Post-flight ``consume_response_bytes`` decrements the remaining byte budget."""
    session_limits.reset_run_budgets_for_tests()
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-resp",
        max_bytes=1_000,
    )
    session_limits.consume_response_bytes(
        token,
        signing_key=_SIGNING_KEY,
        response_bytes=400,
    )
    state = session_limits._BUDGETS["run-mc-resp"]
    assert state.bytes_used == 400


def test_consume_response_bytes_raises_when_over_budget() -> None:
    """Charging past ``max_bytes`` raises ``BudgetExceeded`` (not auth 401)."""
    session_limits.reset_run_budgets_for_tests()
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-resp-over",
        max_bytes=100,
    )
    with pytest.raises(session_limits.BudgetExceeded):
        session_limits.consume_response_bytes(
            token,
            signing_key=_SIGNING_KEY,
            response_bytes=250,
        )


def test_consume_response_bytes_no_byte_claim_is_unlimited() -> None:
    """Tokens without a ``max_bytes`` / ``bytes`` claim are unlimited post-flight.

    The function returns silently without raising and does not charge any
    bytes (the state object is only created to track ``exp`` for pruning,
    but ``bytes_used`` stays at 0 because there is no cap to enforce).
    """
    session_limits.reset_run_budgets_for_tests()
    token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=_SANDBOX_SCOPE,
        run_id="run-mc-resp-unlim",
        container_id="ctr-mc-1",
    )
    # Should not raise even with a very large value.
    session_limits.consume_response_bytes(
        token,
        signing_key=_SIGNING_KEY,
        response_bytes=10**9,
    )
    state = session_limits._BUDGETS["run-mc-resp-unlim"]
    assert state.bytes_used == 0


def test_consume_response_bytes_invalid_claim_raises_budget_exceeded() -> None:
    """Non-int / negative ``max_bytes`` claim is rejected (consistent seam)."""
    session_limits.reset_run_budgets_for_tests()
    exp = int(time.time()) + 3600
    payload = {
        "scope": _SANDBOX_SCOPE,
        "exp": exp,
        "run_id": "run-mc-resp-bad",
        "container_id": "ctr-mc-1",
        "limits": {"bytes": -5},
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(_SIGNING_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    token = f"v1.{body}.{sig}"
    with pytest.raises(session_limits.BudgetExceeded):
        session_limits.consume_response_bytes(
            token,
            signing_key=_SIGNING_KEY,
            response_bytes=10,
        )


def test_consume_response_bytes_combines_with_preflight_request_bytes() -> None:
    """Pre-flight request bytes + post-flight response bytes share the same state."""
    session_limits.reset_run_budgets_for_tests()
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-resp-combine",
        max_bytes=1_000,
    )
    session_limits.consume_run_budget(
        token,
        signing_key=_SIGNING_KEY,
        request_bytes=300,
    )
    session_limits.consume_response_bytes(
        token,
        signing_key=_SIGNING_KEY,
        response_bytes=500,
    )
    state = session_limits._BUDGETS["run-mc-resp-combine"]
    assert state.bytes_used == 800
    with pytest.raises(session_limits.BudgetExceeded):
        session_limits.consume_response_bytes(
            token,
            signing_key=_SIGNING_KEY,
            response_bytes=250,
        )


@pytest.mark.anyio
async def test_web_fetch_charges_response_bytes_against_byte_budget() -> None:
    """The ``/web/fetch`` HTTP path charges the response ``text`` bytes post-flight."""
    session_limits.reset_run_budgets_for_tests()
    # Request body + response must fit under max_bytes so the call succeeds
    # (the byte budget spans both directions).
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-http-resp",
        max_bytes=1_000,
    )
    upstream_text = "x" * 100

    async def _fake_web_fetch_json(payload: dict[str, Any], **_: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": payload["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/plain",
            "text": upstream_text,
            "truncated": False,
        }

    from unittest.mock import patch

    transport = httpx.ASGITransport(app=_proxy_app())
    with patch("sevn.proxy.app.web_fetch_json", side_effect=_fake_web_fetch_json):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/web/fetch",
                json={"url": "https://example.com/"},
                headers={
                    "X-Sevn-Session-Token": token,
                    "X-Sevn-Run-Id": "run-mc-http-resp",
                    "X-Sevn-Container-Id": "ctr-mc-1",
                },
            )

    assert resp.status_code == 200
    state = session_limits._BUDGETS["run-mc-http-resp"]
    assert state.bytes_used >= 100


@pytest.mark.anyio
async def test_web_fetch_response_byte_budget_exhaustion_returns_429() -> None:
    """When the response would exceed the byte budget, ``/web/fetch`` returns ``429``."""
    session_limits.reset_run_budgets_for_tests()
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-http-over",
        max_bytes=50,
    )
    upstream_text = "y" * 200

    async def _fake_web_fetch_json(payload: dict[str, Any], **_: Any) -> tuple[int, dict[str, Any]]:
        return 200, {
            "url": payload["url"],
            "method": "GET",
            "status_code": 200,
            "content_type": "text/plain",
            "text": upstream_text,
            "truncated": False,
        }

    from unittest.mock import patch

    transport = httpx.ASGITransport(app=_proxy_app())
    with patch("sevn.proxy.app.web_fetch_json", side_effect=_fake_web_fetch_json):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/web/fetch",
                json={"url": "https://example.com/"},
                headers={
                    "X-Sevn-Session-Token": token,
                    "X-Sevn-Run-Id": "run-mc-http-over",
                    "X-Sevn-Container-Id": "ctr-mc-1",
                },
            )

    assert resp.status_code == 429
    detail = str(resp.json().get("detail", "")).lower()
    assert "byte budget exceeded" in detail or "budget" in detail


# ---------------------------------------------------------------------------
# Finding 2 — _BUDGETS is pruned when tokens expire
# ---------------------------------------------------------------------------


def test_budget_entry_evicted_when_token_exp_claim_passes() -> None:
    """An entry whose ``exp`` claim is in the past is pruned before lookup."""
    session_limits.reset_run_budgets_for_tests()
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-prune",
        max_bytes=1_000,
        expires_at=int(time.time()) - 1,
    )
    session_limits.consume_run_budget(
        token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    assert "run-mc-prune" in session_limits._BUDGETS
    pruned = session_limits._prune_expired_budgets()
    assert pruned == 1
    assert "run-mc-prune" not in session_limits._BUDGETS


def test_budget_entry_retained_when_token_still_valid() -> None:
    """Active (unexpired) entries are not pruned by ``_prune_expired_budgets``."""
    session_limits.reset_run_budgets_for_tests()
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-keep",
        max_bytes=1_000,
        expires_at=int(time.time()) + 3600,
    )
    session_limits.consume_run_budget(
        token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    pruned = session_limits._prune_expired_budgets()
    assert pruned == 0
    assert "run-mc-keep" in session_limits._BUDGETS


def test_prune_is_lazy_on_subsequent_consume() -> None:
    """``_prune_expired_budgets`` runs opportunistically on the next consume seam."""
    session_limits.reset_run_budgets_for_tests()
    expired_token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-lazy",
        max_bytes=1_000,
        expires_at=int(time.time()) - 1,
    )
    session_limits.consume_run_budget(
        expired_token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    # Manually mark the entry as still tracked (prune would clean it, but we
    # confirm the consume path also prunes on the next access without a
    # manual call).
    fresh_token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-lazy-fresh",
        max_bytes=1_000,
        expires_at=int(time.time()) + 3600,
    )
    session_limits.consume_run_budget(
        fresh_token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    assert "run-mc-lazy" not in session_limits._BUDGETS
    assert "run-mc-lazy-fresh" in session_limits._BUDGETS


# ---------------------------------------------------------------------------
# Finding 3 — per-call random run id (no constant "gateway-egress")
# ---------------------------------------------------------------------------


def test_build_egress_web_headers_fallback_run_id_is_random_per_call() -> None:
    """Two fallback mints must produce different ``X-Sevn-Run-Id`` headers."""
    from sevn.tools.web import build_egress_web_headers

    h1 = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=None,
        proxy_shared_secret="shared-secret",
    )
    h2 = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=None,
        proxy_shared_secret="shared-secret",
    )
    assert h1["X-Sevn-Run-Id"] != h2["X-Sevn-Run-Id"]
    assert h1["X-Sevn-Run-Id"].startswith("gateway-egress-")
    assert h1["X-Sevn-Session-Token"] != h2["X-Sevn-Session-Token"]


def test_build_egress_web_headers_fallback_run_id_decodes_from_token() -> None:
    """The emitted ``X-Sevn-Run-Id`` matches the token payload ``run_id`` claim."""
    from sevn.tools.web import build_egress_web_headers

    h = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=None,
        proxy_shared_secret="shared-secret",
    )
    body = h["X-Sevn-Session-Token"].split(".")[1]
    padded = body + "=" * (-len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    assert payload["run_id"] == h["X-Sevn-Run-Id"]
    assert payload["run_id"] != "gateway-egress"


def test_build_egress_web_headers_explicit_token_run_id_unchanged() -> None:
    """When a session token is supplied, its run id drives ``X-Sevn-Run-Id``."""
    from sevn.proxy.auth import mint_session_token
    from sevn.tools.web import build_egress_web_headers

    token = mint_session_token(
        signing_key="shared-secret",
        scope=_SANDBOX_SCOPE,
        run_id="explicit-run-id",
        container_id="ctr-explicit",
    )
    h = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token,
        proxy_shared_secret="shared-secret",
    )
    assert h["X-Sevn-Run-Id"] == "explicit-run-id"


def test_fallback_run_id_is_unique_across_many_calls() -> None:
    """A small batch of fallback mints must all produce distinct run ids."""
    from sevn.tools.web import build_egress_web_headers

    seen: set[str] = set()
    for _ in range(20):
        h = build_egress_web_headers(
            proxy_url="http://127.0.0.1:8787",
            session_token=None,
            proxy_shared_secret="shared-secret",
        )
        seen.add(h["X-Sevn-Run-Id"])
    assert len(seen) == 20
