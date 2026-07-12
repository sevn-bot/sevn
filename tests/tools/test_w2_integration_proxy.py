"""Wave W2: live ``integration_call`` via egress ``IntegrationProxyClient``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from sevn.config.workspace_config import WorkspaceConfig
from sevn.integrations.github_skill import (
    GithubSkillHooks,
    gh_pr,
    integration_call_from_mapping,
)
from sevn.tools.base import ToolCall
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.integration_proxy_client import build_integration_proxy_client
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.runtime_bindings_factory import apply_readiness_from_bindings
from sevn.tools.runtime_dispatch import RuntimeToolBindings

if TYPE_CHECKING:
    from starlette.requests import Request


async def _fake_integration_post(request: Request) -> JSONResponse:
    body = await request.json()
    service = str(body.get("service") or "")
    method = str(body.get("method") or "")
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    if service == "github" and method == "pulls.list":
        owner = args.get("owner")
        return JSONResponse({"items": [{"number": 3, "owner": owner}]})
    if service == "github":
        return JSONResponse(
            {"detail": "GitHub token not configured (integration.github.token)"},
            status_code=503,
        )
    return JSONResponse({"detail": "unknown"}, status_code=422)


def _fake_proxy_app() -> Starlette:
    return Starlette(routes=[Route("/integration", _fake_integration_post, methods=["POST"])])


@pytest.fixture
def exec_ctx(tmp_path: Path) -> ToolContext:
    workspace_dir = tmp_path / "ws"
    workspace_dir.mkdir()
    return ToolContext(
        session_id="sess",
        workspace_path=workspace_dir,
        workspace_id="wid",
        registry_version=99,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.anyio
async def test_integration_call_round_trips_github_via_fake_proxy(
    exec_ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``integration_call`` POSTs to fake proxy and returns upstream JSON."""
    transport = httpx.ASGITransport(app=_fake_proxy_app())
    proxy_url = "http://fake-proxy"
    client = build_integration_proxy_client(proxy_url=proxy_url, session_token="tok")
    assert client is not None
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=RuntimeToolBindings(integration=client),
    )

    async def _asgi_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=kwargs["proxy_url"].rstrip("/"),
        ) as http:
            response = await http.post(
                kwargs["path"],
                json=kwargs["body"],
                headers=kwargs["headers"],
            )
            data = response.json()
            assert isinstance(data, dict)
            return response.status_code, data

    monkeypatch.setattr(
        "sevn.tools.integration_proxy_client.proxy_post_json",
        _asgi_proxy_post_json,
    )
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="integration_call",
                arguments={
                    "service": "github",
                    "method": "pulls.list",
                    "args": {"owner": "acme", "repo": "app"},
                },
            ),
        ),
    )

    assert envelope["ok"] is True
    assert envelope["data"]["items"][0]["number"] == 3
    assert envelope["data"]["items"][0]["owner"] == "acme"


@pytest.mark.anyio
async def test_integration_call_needs_credential_envelope(
    exec_ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """503 missing-token from proxy maps to PERMISSION_DENIED + needs_key readiness."""
    transport = httpx.ASGITransport(app=_fake_proxy_app())
    client = build_integration_proxy_client(proxy_url="http://fake-proxy")
    assert client is not None
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=RuntimeToolBindings(integration=client),
    )

    async def _asgi_proxy_post_json(**kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=kwargs["proxy_url"].rstrip("/"),
        ) as http:
            response = await http.post(
                kwargs["path"],
                json=kwargs["body"],
                headers=kwargs["headers"],
            )
            data = response.json()
            assert isinstance(data, dict)
            return response.status_code, data

    monkeypatch.setattr(
        "sevn.tools.integration_proxy_client.proxy_post_json",
        _asgi_proxy_post_json,
    )
    envelope = json.loads(
        await executor.dispatch(
            exec_ctx,
            ToolCall(
                name="integration_call",
                arguments={
                    "service": "github",
                    "method": "repos.get",
                    "args": {"owner": "o", "repo": "r"},
                },
            ),
        ),
    )

    assert envelope["ok"] is False
    assert envelope["code"] == ToolResultCode.PERMISSION_DENIED
    assert envelope["data"]["readiness"] == "needs_key"
    assert "token" in envelope["error"].lower()


@pytest.mark.asyncio
async def test_gh_pr_skill_e2e_against_fake_integration() -> None:
    """``list_pull_requests`` resolves end-to-end through injectable integration hook."""
    client = {"calls": [], "responses": {"pulls.list": {"items": [{"number": 42}]}}}
    out = await gh_pr.list_pull_requests(
        GithubSkillHooks(integration_call=integration_call_from_mapping(client)),
        repo="acme/widgets",
        state="open",
    )
    assert out["count"] == 1
    assert out["pull_requests"][0]["number"] == 42
    assert client["calls"][0]["method"] == "pulls.list"
    assert client["calls"][0]["service"] == "github"


@pytest.mark.anyio
async def test_load_tool_integration_call_ready_when_bound(exec_ctx: ToolContext) -> None:
    """Enabled ``integration_call`` exposes ``readiness.status == ready`` via load_tool."""
    client = build_integration_proxy_client(proxy_url="http://127.0.0.1:8787")
    bindings = RuntimeToolBindings(integration=client)
    apply_readiness_from_bindings(
        bindings,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    executor, _ts = build_session_registry(
        registry_version=exec_ctx.registry_version,
        runtime_bindings=bindings,
    )
    raw = await executor.dispatch(
        exec_ctx,
        ToolCall(name="load_tool", arguments={"name": "integration_call"}),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["readiness"]["status"] == "ready"
