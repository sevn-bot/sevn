"""OpenAI Codex OAuth for the onboarding web wizard (W4.3, D6).

Module: sevn.onboarding.openai_oauth
Depends: sevn.security.oauth.login_flow, sevn.security.secrets.factory

Exports:
    WizardCodexOAuthStart — handoff payload for the onboarding OAuth button.
    start_wizard_codex_oauth — begin PKCE flow and await callback in background.
    poll_wizard_codex_oauth — poll flow completion by CSRF ``state``.
    clear_wizard_codex_oauth_flows — reset in-memory flows (tests).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import SecretsBackendSectionConfig
from sevn.onboarding.wizard_credentials import resolve_wizard_secrets_section
from sevn.security.oauth.authorize import AuthorizationFlow, build_authorization_flow
from sevn.security.oauth.credential import CodexOAuthCredential
from sevn.security.oauth.login_flow import complete_codex_oauth_login
from sevn.security.secrets.factory import secrets_chain_from_workspace

_FLOW_TTL_SECONDS = 600.0


@dataclass(frozen=True, slots=True)
class WizardCodexOAuthStart:
    """Handoff payload for the onboarding wizard OAuth button."""

    authorize_url: str
    state: str


@dataclass
class _PendingWizardFlow:
    """In-memory PKCE flow awaiting browser callback."""

    flow: AuthorizationFlow
    content_root: Path
    section: SecretsBackendSectionConfig | None
    expires_at: float
    task: asyncio.Task[None] | None = None
    credential: CodexOAuthCredential | None = None
    error: str | None = None


_pending_flows: dict[str, _PendingWizardFlow] = {}


def _prune_expired_flows() -> None:
    """Drop expired wizard OAuth flows from memory.

    Examples:
        >>> _prune_expired_flows() is None
        True
    """
    now = time.monotonic()
    expired = [key for key, row in _pending_flows.items() if row.expires_at < now]
    for key in expired:
        row = _pending_flows.pop(key, None)
        if row is not None and row.task is not None and not row.task.done():
            row.task.cancel()


async def _run_wizard_flow(state: str) -> None:
    """Background task: await callback, exchange tokens, persist ``oauth.openai``.

    Args:
        state (str): CSRF state key for ``_pending_flows``.

    Examples:
        >>> # Covered indirectly by onboarding API routes.
        >>> True
        True
    """
    row = _pending_flows.get(state)
    if row is None:
        return
    section = resolve_wizard_secrets_section(row.section)
    chain = secrets_chain_from_workspace(row.content_root, section)
    try:
        row.credential = await complete_codex_oauth_login(row.flow, chain)
    except Exception as exc:
        row.error = str(exc)


def start_wizard_codex_oauth(
    content_root: Path,
    *,
    section: SecretsBackendSectionConfig | None,
) -> WizardCodexOAuthStart:
    """Start Codex OAuth for the onboarding wizard and await callback in background.

    Args:
        content_root (Path): Wizard workspace content root for secrets persistence.
        section (SecretsBackendSectionConfig | None): Wizard ``secrets_backend`` section.

    Returns:
        WizardCodexOAuthStart: Browser-openable authorize URL and CSRF ``state``.

    Examples:
        >>> # Requires a running event loop; covered by onboarding wizard tests.
        >>> True
        True
    """
    _prune_expired_flows()
    flow = build_authorization_flow()
    row = _PendingWizardFlow(
        flow=flow,
        content_root=content_root,
        section=section,
        expires_at=time.monotonic() + _FLOW_TTL_SECONDS,
    )
    _pending_flows[flow.state] = row
    row.task = asyncio.create_task(_run_wizard_flow(flow.state))
    return WizardCodexOAuthStart(authorize_url=flow.authorize_url, state=flow.state)


def poll_wizard_codex_oauth(state: str) -> dict[str, Any]:
    """Poll wizard OAuth completion for a given CSRF ``state``.

    Args:
        state (str): ``state`` returned from :func:`start_wizard_codex_oauth`.

    Returns:
        dict[str, Any]: ``{"status": "pending"|"success"|"failed", ...}``.

    Examples:
        >>> poll_wizard_codex_oauth("missing")["status"]
        'failed'
    """
    _prune_expired_flows()
    row = _pending_flows.get(state.strip())
    if row is None:
        return {"status": "failed", "detail": "OAuth flow not found or expired"}
    if row.error:
        return {"status": "failed", "detail": row.error}
    if row.credential is not None:
        cred = row.credential
        return {
            "status": "success",
            "account_id": cred.account_id,
            "expires": cred.expires,
        }
    task = row.task
    if task is not None and task.done() and row.credential is None and not row.error:
        return {"status": "failed", "detail": "OAuth flow ended without a credential"}
    return {"status": "pending"}


def clear_wizard_codex_oauth_flows() -> None:
    """Clear in-memory wizard OAuth flows (tests and wizard shutdown).

    Examples:
        >>> clear_wizard_codex_oauth_flows() is None
        True
    """
    for row in _pending_flows.values():
        if row.task is not None and not row.task.done():
            row.task.cancel()
    _pending_flows.clear()


__all__ = [
    "WizardCodexOAuthStart",
    "clear_wizard_codex_oauth_flows",
    "poll_wizard_codex_oauth",
    "start_wizard_codex_oauth",
]
