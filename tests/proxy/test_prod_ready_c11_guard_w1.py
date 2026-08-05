"""Prod-ready Batch A W1.8 guard — landed C1.1 suites stay green and unmodified (D40).

``tests/proxy/test_auth.py`` and ``tests/proxy/test_post_audit_proxy_auth_w4_red.py``
must not be edited by Batch A. Critical fail-closed / opt-in / boot-warning contracts
are re-asserted here (nested pytest is avoided — it deadlocks under the parent runner).
Full suite greenness is also required at wave close-out.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from sevn.proxy.app import create_app
from sevn.proxy.auth import (
    PROXY_UNCONFIGURED_DETAIL,
    llm_post_auth_failure,
    log_proxy_allow_unauthenticated_boot_warning,
)
from sevn.proxy.settings import ProxySettings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_C11_SUITES = (
    "tests/proxy/test_auth.py",
    "tests/proxy/test_post_audit_proxy_auth_w4_red.py",
)
_UNCONFIGURED_BODY = b'{"detail":"proxy authentication not configured"}'


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    # Use absolute git — repo ``bin/git`` PATH wrapper can hang under nested pytest.
    return subprocess.run(
        ["/usr/bin/git", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _request(*, path: str = "/web/fetch") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_c11_suite_files_unmodified_vs_ci_base() -> None:
    """D40: Batch A must not edit the landed C1.1 regression suites."""
    base = os.environ.get("SEVN_CI_BASE", "origin/pre-0.0.1")
    proc = _git("diff", "--exit-code", base, "--", *_C11_SUITES)
    assert proc.returncode == 0, f"C1.1 suites modified vs {base}:\n{proc.stdout}{proc.stderr}"


def test_c11_fail_closed_503_when_secret_unconfigured() -> None:
    """D40 smoke: deleting the fail-closed branch must break this guard."""
    resp = llm_post_auth_failure(_request(), None)
    assert resp is not None
    assert resp.status_code == 503
    assert resp.body == _UNCONFIGURED_BODY
    assert PROXY_UNCONFIGURED_DETAIL in resp.body.decode()


def test_c11_healthz_unguarded_when_secret_unconfigured() -> None:
    """D40 smoke: ``/healthz`` stays open when the secret is unset."""
    assert llm_post_auth_failure(_request(path="/healthz"), None) is None


@pytest.mark.anyio
async def test_c11_proxy_app_503_on_guarded_route_without_secret() -> None:
    """D40 smoke: ASGI app returns 503 on guarded routes without a secret."""
    app = create_app(
        settings=ProxySettings(anthropic_api_key="ak", openai_api_key="ok"),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/web/fetch", json={"url": "https://example.com"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == PROXY_UNCONFIGURED_DETAIL


def test_c11_allow_unauthenticated_opt_in_still_exported() -> None:
    """D40 smoke: boot-warning helper for the explicit opt-in remains importable."""
    assert callable(log_proxy_allow_unauthenticated_boot_warning)
