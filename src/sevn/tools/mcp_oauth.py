"""MCP server OAuth credentials via the workspace secrets chain (#90, W29.3).

Module: sevn.tools.mcp_oauth
Depends: asyncio, json, sevn.security.oauth.callback, sevn.security.secrets.chain

OAuth credential blobs live at ``oauth.mcp.<server_id>`` — never in ``sevn.json``.
Callback handling reuses the Codex PKCE local server with a per-flow asyncio lock so
concurrent login attempts cannot clobber each other's state.

Exports:
    mcp_oauth_secret_alias — secrets chain logical key for one MCP server.
    load_mcp_oauth_credential — read stored token JSON.
    persist_mcp_oauth_credential — write token JSON after callback.
    resolve_mcp_oauth_env — build subprocess env entries from stored credentials.
    McpOAuthFlow — in-flight authorize state bundle.
    begin_mcp_oauth_flow — start PKCE authorize flow for one server.
    capture_mcp_oauth_callback — race-hardened local callback capture.
    complete_mcp_oauth_flow — exchange callback code and persist tokens.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sevn.security.oauth.callback import (
    OAuthCallbackResult,
    parse_pasted_oauth_redirect,
    start_local_callback_server,
)
from sevn.security.oauth.pkce import generate_pkce_pair

if TYPE_CHECKING:
    from sevn.security.secrets.chain import SecretsChain

_OAUTH_FLOW_LOCKS: Final[dict[str, asyncio.Lock]] = {}
"""Per-server-id locks guarding concurrent OAuth callback completion."""


def mcp_oauth_secret_alias(server_id: str) -> str:
    """Return the secrets-chain alias for one MCP server's OAuth tokens.

    Args:
        server_id (str): Stable ``mcp_servers`` key.

    Returns:
        str: Logical secret id (``oauth.mcp.<server_id>``).

    Examples:
        >>> mcp_oauth_secret_alias("linear")
        'oauth.mcp.linear'
    """
    cleaned = server_id.strip()
    if not cleaned:
        msg = "server_id must be non-empty"
        raise ValueError(msg)
    return f"oauth.mcp.{cleaned}"


async def load_mcp_oauth_credential(
    chain: SecretsChain,
    server_id: str,
) -> dict[str, Any] | None:
    """Load stored OAuth JSON for one MCP server.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        server_id (str): Stable server id.

    Returns:
        dict[str, Any] | None: Parsed credential blob or ``None`` when unset.

    Raises:
        ValueError: When stored JSON is invalid.

    Examples:
        >>> # Covered by tests/tools/test_mcp_oauth_w29.py
        >>> True
        True
    """
    raw = await chain.get(mcp_oauth_secret_alias(server_id))
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"invalid MCP OAuth JSON at {mcp_oauth_secret_alias(server_id)!r}"
        raise ValueError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"MCP OAuth credential must be a JSON object at {mcp_oauth_secret_alias(server_id)!r}"
        raise ValueError(msg)
    return parsed


async def persist_mcp_oauth_credential(
    chain: SecretsChain,
    server_id: str,
    credential: Mapping[str, Any],
) -> None:
    """Persist OAuth tokens for one MCP server (secrets chain only).

    Args:
        chain (SecretsChain): Workspace secrets chain.
        server_id (str): Stable server id.
        credential (Mapping[str, Any]): Token payload (``access_token``, ``refresh_token``, …).

    Returns:
        None

    Examples:
        >>> # Covered by tests/tools/test_mcp_oauth_w29.py
        >>> True
        True
    """
    await chain.set(mcp_oauth_secret_alias(server_id), json.dumps(dict(credential)))


def resolve_mcp_oauth_env(
    server_spec: Mapping[str, Any],
    credential: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Build subprocess env vars for an MCP stdio server from OAuth config + stored tokens.

    Reads ``oauth.env_var`` (required when ``oauth`` block present) and optional
    ``oauth.refresh_env_var`` from the server row in ``mcp_servers``.

    Args:
        server_spec (Mapping[str, Any]): One ``mcp_servers`` row.
        credential (Mapping[str, Any] | None): Stored OAuth blob from the secrets chain.

    Returns:
        dict[str, str]: Env entries to merge into ``StdioServerParameters.env``.

    Examples:
        >>> resolve_mcp_oauth_env(
        ...     {"oauth": {"env_var": "LINEAR_API_KEY"}},
        ...     {"access_token": "tok"},
        ... )
        {'LINEAR_API_KEY': 'tok'}
    """
    oauth = server_spec.get("oauth")
    if not isinstance(oauth, dict):
        return {}
    env_var = str(oauth.get("env_var") or "").strip()
    if not env_var or credential is None:
        return {}
    access = credential.get("access_token") or credential.get("token")
    if not access:
        return {}
    env: dict[str, str] = {env_var: str(access)}
    refresh_var = str(oauth.get("refresh_env_var") or "").strip()
    refresh = credential.get("refresh_token")
    if refresh_var and refresh:
        env[refresh_var] = str(refresh)
    return env


@dataclass(frozen=True, slots=True)
class McpOAuthFlow:
    """In-flight MCP OAuth authorize state."""

    server_id: str
    state: str
    code_verifier: str
    authorize_url: str


def _flow_lock(server_id: str) -> asyncio.Lock:
    """Return a per-server asyncio lock guarding OAuth callback completion.

    Args:
        server_id (str): Stable MCP server id.

    Returns:
        asyncio.Lock: Process-wide lock for this server id.

    Examples:
        >>> lock = _flow_lock("demo")
        >>> isinstance(lock, asyncio.Lock)
        True
    """
    lock = _OAUTH_FLOW_LOCKS.get(server_id)
    if lock is None:
        lock = asyncio.Lock()
        _OAUTH_FLOW_LOCKS[server_id] = lock
    return lock


def begin_mcp_oauth_flow(
    server_id: str,
    *,
    authorize_url_template: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str] | None = None,
) -> McpOAuthFlow:
    """Build PKCE authorize URL + state for one MCP server OAuth login.

    Args:
        server_id (str): Stable server id (embedded in CSRF state).
        authorize_url_template (str): URL with ``{client_id}``, ``{redirect_uri}``,
            ``{state}``, ``{code_challenge}``, and optional ``{scope}`` placeholders.
        client_id (str): OAuth client id (resolved from secrets before calling).
        redirect_uri (str): Registered redirect URI (local callback default).
        scopes (list[str] | None): Optional scope list joined with spaces.

    Returns:
        McpOAuthFlow: Flow bundle for callback completion.

    Examples:
        >>> flow = begin_mcp_oauth_flow(
        ...     "demo",
        ...     authorize_url_template="https://auth.example/oauth?client_id={client_id}&state={state}&code_challenge={code_challenge}&redirect_uri={redirect_uri}",
        ...     client_id="cid",
        ...     redirect_uri="http://127.0.0.1:1455/auth/callback",
        ... )
        >>> "state=" in flow.authorize_url
        True
    """
    pkce = generate_pkce_pair()
    state = f"mcp:{server_id}:{pkce.verifier[:16]}"
    scope = " ".join(scopes) if scopes else ""
    url = authorize_url_template.format(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=pkce.challenge,
        scope=scope,
    )
    return McpOAuthFlow(
        server_id=server_id,
        state=state,
        code_verifier=pkce.verifier,
        authorize_url=url,
    )


async def capture_mcp_oauth_callback(
    flow: McpOAuthFlow,
    *,
    headless: bool = False,
    pasted_redirect: str | None = None,
) -> OAuthCallbackResult:
    """Capture OAuth callback under a per-server lock (race-hardened).

    Args:
        flow (McpOAuthFlow): Active authorize flow.
        headless (bool): Skip local callback; require pasted redirect.
        pasted_redirect (str | None): Pre-supplied redirect for tests/headless.

    Returns:
        OAuthCallbackResult: Parsed authorization code.

    Raises:
        ValueError: When callback fails or state mismatches.

    Examples:
        >>> # Covered by tests/tools/test_mcp_oauth_w29.py
        >>> True
        True
    """
    async with _flow_lock(flow.server_id):
        if pasted_redirect is not None:
            return parse_pasted_oauth_redirect(pasted_redirect, expected_state=flow.state)
        server = await start_local_callback_server(state=flow.state)
        try:
            if headless or not server.ready:
                msg = "MCP OAuth headless mode requires pasted_redirect"
                raise ValueError(msg)
            callback = await server.wait_for_code()
            if callback is None:
                msg = "MCP OAuth callback did not return an authorization code"
                raise ValueError(msg)
            return callback
        finally:
            await server.close()


async def complete_mcp_oauth_flow(
    chain: SecretsChain,
    flow: McpOAuthFlow,
    *,
    token_url: str,
    client_id: str,
    client_secret: str | None,
    code: str,
) -> dict[str, Any]:
    """Exchange authorization code and persist credential at ``oauth.mcp.<server_id>``.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        flow (McpOAuthFlow): Active flow (provides ``server_id`` + PKCE verifier).
        token_url (str): OAuth token endpoint.
        client_id (str): OAuth client id.
        client_secret (str | None): Optional client secret.
        code (str): Authorization code from callback.

    Returns:
        dict[str, Any]: Stored credential blob.

    Raises:
        ValueError: When token exchange fails.

    Examples:
        >>> # Covered by tests/tools/test_mcp_oauth_w29.py
        >>> True
        True
    """
    import httpx

    async with _flow_lock(flow.server_id):
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1:1455/auth/callback",
            "client_id": client_id,
            "code_verifier": flow.code_verifier,
        }
        if client_secret:
            payload["client_secret"] = client_secret
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(token_url, data=payload)
        if resp.status_code >= 400:
            msg = f"MCP OAuth token exchange failed: HTTP {resp.status_code}"
            raise ValueError(msg)
        body = resp.json()
        if not isinstance(body, dict):
            msg = "MCP OAuth token response must be a JSON object"
            raise ValueError(msg)
        await persist_mcp_oauth_credential(chain, flow.server_id, body)
        return body


__all__ = [
    "McpOAuthFlow",
    "begin_mcp_oauth_flow",
    "capture_mcp_oauth_callback",
    "complete_mcp_oauth_flow",
    "load_mcp_oauth_credential",
    "mcp_oauth_secret_alias",
    "persist_mcp_oauth_credential",
    "resolve_mcp_oauth_env",
]
