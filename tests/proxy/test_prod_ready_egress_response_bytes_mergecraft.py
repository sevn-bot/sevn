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


def _binding_headers(token: str, run_id: str, container_id: str) -> dict[str, str]:
    """Build a complete header set for an HTTP ``/web/fetch`` call.

    Includes the proof-of-possession binding signature required by the proxy
    guard middleware (PR #245 Codex finding 5): without it the request would
    fail with 401 even though the bearer token and binding headers are valid.
    """
    canonical = f"container_id={container_id}\nrun_id={run_id}".encode()
    signature = hmac.new(_SERVICE_SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    return {
        "X-Sevn-Session-Token": token,
        "X-Sevn-Run-Id": run_id,
        "X-Sevn-Container-Id": container_id,
        "X-Sevn-Binding-Signature": signature,
    }


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
                headers=_binding_headers(token, "run-mc-http-resp", "ctr-mc-1"),
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
                headers=_binding_headers(token, "run-mc-http-over", "ctr-mc-1"),
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


def test_prune_runs_on_unbudgeted_consume_run_budget() -> None:
    """``_prune_expired_budgets`` runs on the unbudgeted early-return path of consume_run_budget.

    Closes the mergecraft finding (review 4886120267) that the unbudgeted
    default sandbox token and the per-call random ``run_id`` gateway fallback
    bypassed pruning, leaving entries to grow unbounded.
    """
    session_limits.reset_run_budgets_for_tests()
    expired_token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-prune-unbudgeted",
        max_bytes=1_000,
        expires_at=int(time.time()) - 1,
    )
    session_limits.consume_run_budget(
        expired_token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    assert "run-mc-prune-unbudgeted" in session_limits._BUDGETS
    # Now consume an *unbudgeted* token (no max_requests / max_bytes / limits).
    # The entry above must be evicted as part of that consume, even though
    # the consume itself returns silently without enforcing a cap.
    unbudgeted_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=_SANDBOX_SCOPE,
        run_id="run-mc-unbudgeted-trigger",
        container_id="ctr-mc-1",
    )
    session_limits.consume_run_budget(
        unbudgeted_token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    assert "run-mc-prune-unbudgeted" not in session_limits._BUDGETS
    assert "run-mc-unbudgeted-trigger" in session_limits._BUDGETS


def test_prune_runs_on_unbudgeted_consume_response_bytes() -> None:
    """``_prune_expired_budgets`` runs on the unbudgeted early-return path of consume_response_bytes.

    Same seam as ``test_prune_runs_on_unbudgeted_consume_run_budget`` but
    exercising the post-flight ``consume_response_bytes`` path. Without the
    mergecraft-asked fix, the unbudgeted ``max_bytes is None`` early-return
    skipped pruning and an expired entry stayed in ``_BUDGETS`` until the
    proxy restarted.
    """
    session_limits.reset_run_budgets_for_tests()
    expired_token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-mc-prune-resp-unbudgeted",
        max_bytes=1_000,
        expires_at=int(time.time()) - 1,
    )
    session_limits.consume_run_budget(
        expired_token,
        signing_key=_SIGNING_KEY,
        request_bytes=10,
    )
    assert "run-mc-prune-resp-unbudgeted" in session_limits._BUDGETS
    unbudgeted_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=_SANDBOX_SCOPE,
        run_id="run-mc-resp-unbudgeted-trigger",
        container_id="ctr-mc-1",
    )
    session_limits.consume_response_bytes(
        unbudgeted_token,
        signing_key=_SIGNING_KEY,
        response_bytes=10,
    )
    assert "run-mc-prune-resp-unbudgeted" not in session_limits._BUDGETS
    assert "run-mc-resp-unbudgeted-trigger" in session_limits._BUDGETS


# ---------------------------------------------------------------------------
# Finding 3 — fallback mint removed (PR #245 follow-up to Codex finding 3)
# ---------------------------------------------------------------------------
#
# Earlier the mergecraft review asked for a per-call random ``run_id`` to avoid
# the constant ``"gateway-egress"`` reuse; that fix shipped in ``bb152c5f``.
# The follow-up review concluded the synthetic fallback should be removed
# entirely: it produced unbounded ``_BUDGETS`` growth for the unbudgeted mint
# path and never carried a real per-run binding. Callers must now inject a
# scoped ``SEVN_SESSION_TOKEN``; the helper raises
# :class:`ProxySessionTokenRequiredError` when the token is absent.


def test_build_egress_web_headers_rejects_missing_session_token() -> None:
    """Without a session token the helper raises ``ProxySessionTokenRequiredError``."""
    import pytest

    from sevn.tools.web import (
        ProxySessionTokenRequiredError,
        build_egress_web_headers,
    )

    with pytest.raises(ProxySessionTokenRequiredError) as caught:
        build_egress_web_headers(
            proxy_url="http://127.0.0.1:8787",
            session_token=None,
            proxy_shared_secret="shared-secret",
        )
    assert "SEVN_SESSION_TOKEN" in str(caught.value)
    assert "fallback" in str(caught.value).lower()


def test_build_egress_web_headers_rejects_blank_session_token() -> None:
    """Blank / whitespace-only session tokens are also rejected."""
    import pytest

    from sevn.tools.web import (
        ProxySessionTokenRequiredError,
        build_egress_web_headers,
    )

    with pytest.raises(ProxySessionTokenRequiredError):
        build_egress_web_headers(
            proxy_url="http://127.0.0.1:8787",
            session_token="   ",
            proxy_shared_secret="shared-secret",
        )


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
    assert h["X-Sevn-Container-Id"] == "ctr-explicit"
    # PoP signature is always emitted (PR #245 Codex finding 5).
    assert "x-sevn-binding-signature" in h


def test_build_egress_web_headers_binding_signature_is_deterministic() -> None:
    """The PoP signature is deterministic for a given (container_id, run_id, secret) tuple."""
    from sevn.proxy.auth import mint_session_token
    from sevn.tools.web import build_egress_web_headers

    token = mint_session_token(
        signing_key="shared-secret",
        scope=_SANDBOX_SCOPE,
        run_id="run-pop",
        container_id="ctr-pop",
    )
    h1 = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token,
        proxy_shared_secret="shared-secret",
    )
    h2 = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token,
        proxy_shared_secret="shared-secret",
    )
    assert h1["x-sevn-binding-signature"] == h2["x-sevn-binding-signature"]


def test_build_egress_web_headers_binding_signature_changes_with_secret() -> None:
    """The PoP signature is keyed by the shared secret."""
    from sevn.proxy.auth import mint_session_token
    from sevn.tools.web import build_egress_web_headers

    token = mint_session_token(
        signing_key="shared-secret",
        scope=_SANDBOX_SCOPE,
        run_id="run-pop",
        container_id="ctr-pop",
    )
    h_a = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token,
        proxy_shared_secret="secret-a",
    )
    h_b = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token,
        proxy_shared_secret="secret-b",
    )
    assert h_a["x-sevn-binding-signature"] != h_b["x-sevn-binding-signature"]


def test_build_egress_web_headers_binding_signature_changes_with_run_id() -> None:
    """The PoP signature changes when the run id claim changes."""
    from sevn.proxy.auth import mint_session_token
    from sevn.tools.web import build_egress_web_headers

    token_a = mint_session_token(
        signing_key="shared-secret",
        scope=_SANDBOX_SCOPE,
        run_id="run-a",
        container_id="ctr",
    )
    token_b = mint_session_token(
        signing_key="shared-secret",
        scope=_SANDBOX_SCOPE,
        run_id="run-b",
        container_id="ctr",
    )
    h_a = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token_a,
        proxy_shared_secret="shared-secret",
    )
    h_b = build_egress_web_headers(
        proxy_url="http://127.0.0.1:8787",
        session_token=token_b,
        proxy_shared_secret="shared-secret",
    )
    assert h_a["x-sevn-binding-signature"] != h_b["x-sevn-binding-signature"]


# ---------------------------------------------------------------------------
# Finding 4 — redirect target is re-checked against the session allowlist
# ---------------------------------------------------------------------------


def test_web_fetch_blocks_redirect_to_unlisted_host() -> None:
    """An allowed host that redirects to a non-allowlisted host is blocked (PR #245 finding 4).

    Earlier the proxy only checked the initial URL against the session token
    allowlist; an allowed host could redirect to an unlisted host and bypass
    the per-run allowlist. The fix threads ``allow_redirect_to`` through
    ``web_fetch_json`` → ``_request_upstream`` / ``_fetch_upstream_streaming``
    so every redirect target is re-validated. End-to-end redirect-loop coverage
    is provided by the unit test
    ``test_build_redirect_allowlist_check_blocks_unlisted_target`` below; this
    test pins the contract that a ``ValueError`` raised from the closure
    propagates through ``_egress_block_status`` to a ``403`` detail.
    """
    from sevn.proxy.web_forward import _egress_block_status

    def _redirect_to_blocked(target: str) -> None:
        raise ValueError(
            "redirect target not on session allowlist: destination host "
            "'blocked.example.com' is not on the session allowlist"
        )

    with pytest.raises(ValueError, match="allowlist"):
        _redirect_to_blocked("https://blocked.example.com/")

    # The status-mapping the real ``web_fetch_json`` uses is what surfaces to
    # the sandbox — guard that a redirect-allowlist ``ValueError`` becomes 403.
    status = _egress_block_status(
        "redirect target not on session allowlist: destination host "
        "'blocked.example.com' is not on the session allowlist"
    )
    assert status == 403


def test_build_redirect_allowlist_check_returns_none_without_session_token() -> None:
    """Without a session token, the proxy returns ``None`` (no allowlist enforcement).

    PR #245 Codex finding 4: only session-token callers carry an allowlist; the
    helper no-ops for unauthenticated callers so unit paths without a token
    keep working (the proxy guard rejects the request upstream of this hook).
    """
    from unittest.mock import MagicMock

    from sevn.proxy.app import _build_redirect_allowlist_check

    req = MagicMock()
    req.headers = {}
    assert (
        _build_redirect_allowlist_check(req, settings=ProxySettings(proxy_shared_secret="k"))
        is None
    )


def test_build_redirect_allowlist_check_blocks_unlisted_target() -> None:
    """The closure raises ``ValueError`` when the redirect target is unlisted."""
    from unittest.mock import MagicMock

    from sevn.proxy.app import _build_redirect_allowlist_check

    token = mint_session_token(
        signing_key=_SERVICE_SECRET,
        scope=_SANDBOX_SCOPE,
        run_id="run-mc-redirect2",
        container_id="ctr-mc-redirect2",
        destination_allowed=["allowed.example.com"],
    )
    req = MagicMock()
    req.headers = {"x-sevn-session-token": token}
    check = _build_redirect_allowlist_check(
        req, settings=ProxySettings(proxy_shared_secret=_SERVICE_SECRET)
    )
    assert check is not None
    import pytest

    with pytest.raises(ValueError, match="allowlist"):
        check("https://blocked.example.com/")


def test_build_redirect_allowlist_check_passes_listed_target() -> None:
    """The closure is a no-op when the redirect target is on the allowlist."""
    from unittest.mock import MagicMock

    from sevn.proxy.app import _build_redirect_allowlist_check

    token = mint_session_token(
        signing_key=_SERVICE_SECRET,
        scope=_SANDBOX_SCOPE,
        run_id="run-mc-redirect3",
        container_id="ctr-mc-redirect3",
        destination_allowed=["allowed.example.com", "other.example.com"],
    )
    req = MagicMock()
    req.headers = {"x-sevn-session-token": token}
    check = _build_redirect_allowlist_check(
        req, settings=ProxySettings(proxy_shared_secret=_SERVICE_SECRET)
    )
    assert check is not None
    # No raise on listed hosts.
    check("https://allowed.example.com/path")
    check("https://other.example.com/")
