"""Injectable hooks for bundled GitHub skill scripts.

Module: sevn.integrations.github_skill.hooks
Depends: httpx, os, sevn.config.settings, sevn.tools.integration_gh_repo, sevn.tools.web

Exports:
    GithubSkillHooks — integration delegate for GitHub REST via proxy.
    resolve_github_skill_hooks — build hooks from env or explicit overrides.
    integration_call_from_mapping — async caller from injectable mapping client.
    proxy_github_integration_call — build proxy ``/integration`` caller from env.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sevn.config.settings import ProcessSettings
from sevn.tools.integration_gh_repo import GITHUB_INTEGRATION_SERVICE
from sevn.tools.web import build_egress_web_headers, proxy_post_json

IntegrationCallFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
_PROXY_INTEGRATION_PATH = "/integration"


@dataclass
class GithubSkillHooks:
    """Delegates for GitHub skill scripts and tests.

    Attributes:
        integration_call (IntegrationCallFn | None): Async ``(method, args) -> payload``.
    """

    integration_call: IntegrationCallFn | None = None


def integration_call_from_mapping(client: dict[str, Any]) -> IntegrationCallFn:
    """Wrap a test double recording ``integration_call`` invocations.

    Args:
        client (dict[str, Any]): Object with ``calls: list`` and ``responses: dict``.

    Returns:
        IntegrationCallFn: Async delegate keyed by ``method``.

    Examples:
        >>> import asyncio
        >>> fake: dict[str, object] = {"calls": [], "responses": {"pulls.list": {"items": []}}}
        >>> hook = integration_call_from_mapping(fake)
        >>> asyncio.run(hook("pulls.list", {"owner": "o", "repo": "r"}))
        {'items': []}
        >>> fake["calls"]
        [{'service': 'github', 'method': 'pulls.list', 'args': {'owner': 'o', 'repo': 'r'}}]
    """

    async def _call(method: str, args: dict[str, Any]) -> dict[str, Any]:
        calls = client.setdefault("calls", [])
        if isinstance(calls, list):
            calls.append(
                {
                    "service": GITHUB_INTEGRATION_SERVICE,
                    "method": method,
                    "args": dict(args),
                },
            )
        responses = client.get("responses", {})
        if isinstance(responses, dict) and method in responses:
            payload = responses[method]
            return payload if isinstance(payload, dict) else {"result": payload}
        return {"ok": True, "method": method, "args": dict(args)}

    return _call


def _resolve_process_egress() -> tuple[str | None, str | None, str | None]:
    """Read proxy URL, session token, and shared secret from process env.

    Returns:
        tuple[str | None, str | None, str | None]: ``(proxy_url, session_token, shared_secret)``.

    Examples:
        >>> isinstance(_resolve_process_egress(), tuple)
        True
    """
    ps = ProcessSettings()
    proxy_url = (ps.proxy_url or "").strip() or None
    session_token = (ps.session_token or "").strip() or None
    shared_secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip() or None
    return proxy_url, session_token, shared_secret


def proxy_github_integration_call() -> IntegrationCallFn:
    """Build an async caller that POSTs to egress proxy ``/integration``.

    Returns:
        IntegrationCallFn: Posts ``{service, method, args}`` with session headers.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(proxy_github_integration_call())
        True
    """

    async def _call(method: str, args: dict[str, Any]) -> dict[str, Any]:
        proxy_url, session_token, shared_secret = _resolve_process_egress()
        if not proxy_url:
            msg = "SEVN_PROXY_URL is not configured; GitHub skills require the egress proxy"
            raise RuntimeError(msg)
        body = {
            "service": GITHUB_INTEGRATION_SERVICE,
            "method": method,
            "args": dict(args),
        }
        headers = build_egress_web_headers(
            proxy_url=proxy_url,
            session_token=session_token,
            proxy_shared_secret=shared_secret,
        )
        status, data = await proxy_post_json(
            proxy_url=proxy_url,
            path=_PROXY_INTEGRATION_PATH,
            body=body,
            headers=headers,
        )
        if status >= 400:
            detail = str(data.get("detail") or data.get("error") or f"proxy status {status}")
            raise RuntimeError(detail)
        return data

    return _call


def resolve_github_skill_hooks(
    workspace: object | None = None,
    *,
    overrides: GithubSkillHooks | None = None,
) -> GithubSkillHooks:
    """Resolve default GitHub skill hooks for bundled scripts.

    Args:
        workspace (object | None, optional): Reserved for future config hooks.
        overrides (GithubSkillHooks | None, optional): Explicit hook bundle for tests.

    Returns:
        GithubSkillHooks: Resolved hook bundle.

    Examples:
        >>> hooks = resolve_github_skill_hooks(overrides=GithubSkillHooks())
        >>> hooks.integration_call is None
        True
    """
    _ = workspace
    if overrides is not None:
        return overrides
    return GithubSkillHooks(integration_call=proxy_github_integration_call())
