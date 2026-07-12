"""Codex OAuth login completion helpers (W4 — CLI + onboarding).

Module: sevn.security.oauth.login_flow
Depends: sevn.security.oauth.{authorize,callback,storage,token_client}

Exports:
    load_codex_oauth_credential_from_workspace — read ``oauth.openai`` for CLI status.
    capture_codex_oauth_callback — local callback or pasted redirect (D5).
    exchange_and_persist_codex_oauth — code→token and persist at ``oauth.openai``.
    complete_codex_oauth_login — capture + exchange + persist in one call.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any

from sevn.security.oauth.callback import (
    OAuthCallbackResult,
    parse_pasted_oauth_redirect,
    start_local_callback_server,
)
from sevn.security.oauth.storage import load_codex_oauth_credential, persist_codex_oauth_credential
from sevn.security.oauth.token_client import exchange_authorization_code

if TYPE_CHECKING:
    from sevn.cli.workspace import BoundWorkspace
    from sevn.security.oauth.authorize import AuthorizationFlow
    from sevn.security.oauth.credential import CodexOAuthCredential
    from sevn.security.secrets.chain import SecretsChain


def load_codex_oauth_credential_from_workspace(bound: BoundWorkspace) -> dict[str, Any] | None:
    """Load the Codex OAuth credential blob from the bound workspace secrets chain.

    Args:
        bound (BoundWorkspace): CLI-bound workspace (``SEVN_HOME``).

    Returns:
        dict[str, Any] | None: ``{access, refresh, expires, account_id}`` or ``None``.

    Examples:
        >>> # Covered by tests/cli/test_providers_oauth_openai.py via patch.
        >>> True
        True
    """
    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.security.secrets.factory import secrets_chain_from_workspace

    chain = secrets_chain_from_workspace(bound.layout.content_root, bound.config.secrets_backend)
    credential = run_sync_coro(load_codex_oauth_credential(chain))
    if credential is None:
        return None
    return credential.model_dump()


async def capture_codex_oauth_callback(
    flow: AuthorizationFlow,
    *,
    headless: bool = False,
    pasted_redirect: str | None = None,
) -> OAuthCallbackResult:
    """Capture authorization code via local callback or manual paste (D5).

    Args:
        flow (AuthorizationFlow): PKCE/state bundle from ``build_authorization_flow``.
        headless (bool): When ``True``, skip local callback and require paste input.
        pasted_redirect (str | None): Pre-supplied redirect URL/code (non-interactive tests).

    Returns:
        OAuthCallbackResult: Parsed authorization code and state.

    Raises:
        ValueError: When callback/paste fails or input is missing in headless mode.

    Examples:
        >>> # Covered by CLI/onboarding integration callers.
        >>> True
        True
    """
    server = await start_local_callback_server(state=flow.state)
    try:
        if pasted_redirect is not None:
            return parse_pasted_oauth_redirect(pasted_redirect, expected_state=flow.state)
        if headless or not server.ready:
            if not sys.stdin.isatty():
                msg = "headless OAuth requires pasted_redirect or an interactive terminal"
                raise ValueError(msg)
            raw = (
                await asyncio.to_thread(
                    input,
                    "Paste the redirect URL or authorization code: ",
                )
            ).strip()
            return parse_pasted_oauth_redirect(raw, expected_state=flow.state)
        callback = await server.wait_for_code()
        if callback is None:
            msg = "OAuth callback did not return an authorization code"
            raise ValueError(msg)
        return callback
    finally:
        await server.close()


async def exchange_and_persist_codex_oauth(
    chain: SecretsChain,
    *,
    code: str,
    code_verifier: str,
) -> CodexOAuthCredential:
    """Exchange authorization code for tokens and persist at ``oauth.openai`` (D2).

    Args:
        chain (SecretsChain): Workspace secrets chain.
        code (str): Authorization code from callback or paste.
        code_verifier (str): PKCE verifier from ``AuthorizationFlow.pkce``.

    Returns:
        CodexOAuthCredential: Stored credential blob.

    Raises:
        ValueError: When token exchange fails.

    Examples:
        >>> # Covered by tests/security/oauth/test_token_client.py and CLI callers.
        >>> True
        True
    """
    result = await exchange_authorization_code(code=code, code_verifier=code_verifier)
    if result.type != "success" or result.credential is None:
        msg = "OAuth token exchange failed"
        raise ValueError(msg)
    await persist_codex_oauth_credential(chain, result.credential)
    return result.credential


async def complete_codex_oauth_login(
    flow: AuthorizationFlow,
    chain: SecretsChain,
    *,
    headless: bool = False,
    pasted_redirect: str | None = None,
) -> CodexOAuthCredential:
    """Run D5 capture, token exchange, and ``oauth.openai`` persistence.

    Args:
        flow (AuthorizationFlow): PKCE/state bundle from ``build_authorization_flow``.
        chain (SecretsChain): Workspace secrets chain.
        headless (bool): Use manual paste fallback instead of local callback.
        pasted_redirect (str | None): Optional pre-supplied redirect for non-interactive flows.

    Returns:
        CodexOAuthCredential: Stored credential.

    Examples:
        >>> # Covered by ``sevn providers oauth login`` and onboarding wizard.
        >>> True
        True
    """
    callback = await capture_codex_oauth_callback(
        flow,
        headless=headless,
        pasted_redirect=pasted_redirect,
    )
    return await exchange_and_persist_codex_oauth(
        chain,
        code=callback.code,
        code_verifier=flow.pkce.verifier,
    )


__all__ = [
    "capture_codex_oauth_callback",
    "complete_codex_oauth_login",
    "exchange_and_persist_codex_oauth",
    "load_codex_oauth_credential_from_workspace",
]
