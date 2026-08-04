"""Tests for proxy ``POST /integration`` GitHub forwarder (Wave W2)."""

from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from tests.proxy.conftest import proxy_auth_headers, proxy_test_settings

from sevn.proxy.app import create_app
from sevn.proxy.integration import github as github_module
from sevn.proxy.integration.github import GITHUB_METHODS

if TYPE_CHECKING:
    from sevn.proxy.settings import ProxySettings


def _settings(**kwargs: str | None) -> ProxySettings:
    data = {
        "anthropic_api_key": kwargs.get("anthropic_api_key") or "ak",
        "openai_api_key": kwargs.get("openai_api_key") or "ok",
    }
    if "proxy_shared_secret" in kwargs:
        data["proxy_shared_secret"] = kwargs.get("proxy_shared_secret")
    return proxy_test_settings(**data)


@pytest.mark.anyio
async def test_integration_github_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing GitHub token returns 503 with credential detail."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    app = create_app(settings=_settings())
    app.state.secrets_cache = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=proxy_auth_headers()
    ) as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "github",
                "method": "pulls.list",
                "args": {"owner": "acme", "repo": "app"},
            },
        )
    assert resp.status_code == 503
    assert "token" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_integration_github_pulls_list_forwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pulls.list`` GETs GitHub pulls and wraps array as ``items``."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    captured: dict[str, Any] = {}

    async def fake_github_request(
        *,
        method: str,
        path: str,
        token: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        _ = (token, json_body)
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        return 200, [{"number": 7, "title": "Fix"}]

    monkeypatch.setattr(
        "sevn.proxy.integration.github._github_request",
        fake_github_request,
    )

    app = create_app(settings=_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=proxy_auth_headers()
    ) as client:
        resp = await client.post(
            "/integration",
            json={
                "service": "github",
                "method": "pulls.list",
                "args": {"owner": "acme", "repo": "app", "state": "open"},
            },
        )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["number"] == 7
    assert captured["method"] == "GET"
    assert captured["path"] == "/repos/acme/app/pulls"
    assert captured["params"] == {"state": "open"}


# --- unknown-method response regression -----------------------------------------------
#
# The dispatcher validated owner/repo BEFORE checking whether the method was supported,
# and the fallback returned only "unknown github method: {method}". The LLM executor then
# guessed `search.repositories`, `repos.get_content`, `request` and
# `GET /repos/{owner}/{repo}` across four rounds; because `search.repositories` has no
# owner/repo it was misrouted into the gateway's "resolve owner/repo from
# self_improve.hub.repo" retry path, costing an extra upstream roundtrip.


async def _post_github(method: str, args: dict[str, Any]) -> httpx.Response:
    """POST one ``service=github`` integration call against a fresh proxy app."""
    app = create_app(settings=_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=proxy_auth_headers()
    ) as client:
        return await client.post(
            "/integration",
            json={"service": "github", "method": method, "args": args},
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method",
    [
        "search.repositories",
        "repos.get_content",
        "request",
        "GET /repos/{owner}/{repo}",
    ],
)
async def test_integration_github_unknown_method_enumerates_supported(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """Each real-world guess gets a terminal 422 naming it plus the full allowlist."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    resp = await _post_github(method, {"owner": "acme", "repo": "app"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["method"] == method
    assert body["supported"] == list(GITHUB_METHODS)
    assert body["supported"]
    assert method in body["detail"]
    assert "supported github methods" in body["detail"]
    assert "pulls.list" in body["detail"]


@pytest.mark.anyio
async def test_integration_github_unknown_method_checked_before_owner_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordering regression: `search.repositories` has no owner/repo and must not be
    reported as a missing-owner/repo error, which is what triggered the wasted
    self_improve.hub.repo resolution retry.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    resp = await _post_github("search.repositories", {})

    assert resp.status_code == 422
    body = resp.json()
    detail = str(body.get("detail", ""))
    assert "owner and repo are required" not in detail
    assert "unknown github method" in detail
    assert body["method"] == "search.repositories"


@pytest.mark.anyio
async def test_integration_github_valid_method_still_requires_owner_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: the owner/repo guard is still enforced for a supported method."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    resp = await _post_github("pulls.list", {})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "owner and repo are required"


def test_github_methods_allowlist_matches_implemented_branches() -> None:
    """Drift guard: a dispatch branch without an allowlist entry is unreachable.

    The early ``method not in GITHUB_METHODS`` return means any ``if method == "..."``
    branch added without a matching allowlist entry would be silently dead code.
    """
    tree = ast.parse(inspect.getsource(github_module))
    implemented: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.Eq):
            continue
        left = node.left
        right = node.comparators[0]
        if not isinstance(left, ast.Name) or left.id != "method":
            continue
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            implemented.add(right.value)

    assert implemented, 'no `if method == "..."` dispatch branches found'
    assert implemented == set(GITHUB_METHODS)
    assert len(GITHUB_METHODS) == len(set(GITHUB_METHODS))
