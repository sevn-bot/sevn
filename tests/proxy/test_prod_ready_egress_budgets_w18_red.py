"""Batch E W18 RED — destination allowlist + per-run budgets (C7.3).

Contracts land in W20: allowlist and request/byte budgets live on the session-token
payload and are enforced proxy-side before forward. Budget exhaustion must be
distinguishable from auth failure (not a bare 401).

xfail map: W18.4-W18.5 -> W20.
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

from sevn.proxy.app import create_app
from sevn.proxy.settings import ProxySettings

_SERVICE_SECRET = "prod-ready-e-budget-secret-at-least-32"
_SIGNING_KEY = _SERVICE_SECRET
_SANDBOX_SCOPE = "sandbox"


def _mint_budgeted_token(
    *,
    signing_key: str,
    run_id: str,
    allowlist: list[str] | None = None,
    max_requests: int | None = None,
    max_bytes: int | None = None,
    container_id: str = "ctr-budget-1",
    expires_at: int | None = None,
) -> str:
    """Future mint shape (W20): allowlist + per-run request/byte budgets in payload."""
    exp = expires_at if expires_at is not None else int(time.time()) + 3600
    payload: dict[str, Any] = {
        "scope": _SANDBOX_SCOPE,
        "exp": exp,
        "run_id": run_id,
        "container_id": container_id,
    }
    if allowlist is not None:
        payload["allowlist"] = allowlist
    if max_requests is not None:
        payload["max_requests"] = max_requests
    if max_bytes is not None:
        payload["max_bytes"] = max_bytes
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"v1.{body}.{sig}"


def _proxy_app() -> Any:
    return create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=_SERVICE_SECRET,
        ),
    )


# ---------------------------------------------------------------------------
# W18.4 — destination allowlist (xfail → W20, C7.3)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W20: destination allowlist", strict=False)
def test_w18_4_destination_allowed_when_host_in_allowlist() -> None:
    from sevn.proxy.session_limits import destination_allowed

    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-allow",
        allowlist=["allowed.example"],
    )
    assert (
        destination_allowed(
            token,
            signing_key=_SIGNING_KEY,
            destination="https://allowed.example/path",
        )
        is True
    )


@pytest.mark.xfail(reason="green after W20: destination allowlist", strict=False)
def test_w18_4_destination_rejected_when_host_not_in_allowlist() -> None:
    from sevn.proxy.session_limits import DestinationNotAllowed, destination_allowed

    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-allow",
        allowlist=["allowed.example"],
    )
    with pytest.raises(DestinationNotAllowed):
        destination_allowed(
            token,
            signing_key=_SIGNING_KEY,
            destination="https://evil.example/",
        )


@pytest.mark.xfail(reason="green after W20: destination allowlist", strict=False)
@pytest.mark.anyio
async def test_w18_4_http_rejects_out_of_allowlist_destination() -> None:
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-allow",
        allowlist=["allowed.example"],
    )
    transport = httpx.ASGITransport(app=_proxy_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post(
            "/web/fetch",
            json={"url": "https://allowed.example/"},
            headers={
                "X-Sevn-Session-Token": token,
                "X-Sevn-Run-Id": "run-allow",
                "X-Sevn-Container-Id": "ctr-budget-1",
            },
        )
        denied = await client.post(
            "/web/fetch",
            json={"url": "https://evil.example/"},
            headers={
                "X-Sevn-Session-Token": token,
                "X-Sevn-Run-Id": "run-allow",
                "X-Sevn-Container-Id": "ctr-budget-1",
            },
        )
    assert ok.status_code != 401
    assert denied.status_code in (403, 422)
    detail = str(denied.json().get("detail", "")).lower()
    assert "allowlist" in detail or "destination" in detail
    assert denied.status_code != 401


# ---------------------------------------------------------------------------
# W18.5 — per-run request-count and byte budgets (xfail → W20, C7.3)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W20: per-run request/byte budgets", strict=False)
def test_w18_5_request_budget_exhausted_raises_distinguishable_error() -> None:
    from sevn.proxy.session_limits import BudgetExceeded, consume_run_budget

    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-req-budget",
        max_requests=1,
        max_bytes=1_000_000,
    )
    consume_run_budget(token, signing_key=_SIGNING_KEY, request_bytes=10)
    with pytest.raises(BudgetExceeded) as exc_info:
        consume_run_budget(token, signing_key=_SIGNING_KEY, request_bytes=10)
    msg = str(exc_info.value).lower()
    assert "budget" in msg or "request" in msg


@pytest.mark.xfail(reason="green after W20: per-run request/byte budgets", strict=False)
def test_w18_5_byte_budget_exhausted_raises_distinguishable_error() -> None:
    from sevn.proxy.session_limits import BudgetExceeded, consume_run_budget

    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-byte-budget",
        max_requests=100,
        max_bytes=100,
    )
    with pytest.raises(BudgetExceeded) as exc_info:
        consume_run_budget(token, signing_key=_SIGNING_KEY, request_bytes=250)
    msg = str(exc_info.value).lower()
    assert "budget" in msg or "byte" in msg


@pytest.mark.xfail(reason="green after W20: per-run request/byte budgets", strict=False)
@pytest.mark.anyio
async def test_w18_5_http_budget_exhaustion_not_confused_with_auth_failure() -> None:
    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-http-budget",
        allowlist=["example.com"],
        max_requests=1,
        max_bytes=1_000_000,
    )
    headers = {
        "X-Sevn-Session-Token": token,
        "X-Sevn-Run-Id": "run-http-budget",
        "X-Sevn-Container-Id": "ctr-budget-1",
    }
    transport = httpx.ASGITransport(app=_proxy_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers=headers,
        )
        second = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers=headers,
        )
    assert first.status_code != 401
    assert second.status_code in (429, 403, 422)
    assert second.status_code != 401
    detail = str(second.json().get("detail", "")).lower()
    assert "budget" in detail


@pytest.mark.xfail(reason="green after W20: per-run request/byte budgets", strict=False)
@pytest.mark.anyio
async def test_w18_5_concurrent_same_token_budget_replies_consistent() -> None:
    """Same run-bound credential — concurrent consumes must not race-bypass the budget."""
    import asyncio

    from sevn.proxy.session_limits import BudgetExceeded, consume_run_budget

    token = _mint_budgeted_token(
        signing_key=_SIGNING_KEY,
        run_id="run-concurrent-budget",
        max_requests=1,
        max_bytes=1_000_000,
    )

    async def _consume() -> str:
        try:
            await asyncio.to_thread(
                consume_run_budget,
                token,
                signing_key=_SIGNING_KEY,
                request_bytes=1,
            )
            return "ok"
        except BudgetExceeded:
            return "budget"
        except Exception as exc:
            return f"err:{type(exc).__name__}"

    results = await asyncio.gather(_consume(), _consume())
    assert sorted(results) == ["budget", "ok"]
