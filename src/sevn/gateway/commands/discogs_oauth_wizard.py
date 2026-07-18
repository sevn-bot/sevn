"""Discogs OAuth 1.0a Telegram setup wizard (D20 / thermos gate).

Module: sevn.gateway.commands.discogs_oauth_wizard
Depends: sevn.integrations.discogs.oauth, sevn.security.secrets.factory

Exports:
    cleanup_discogs_oauth_interim_secrets — purge handshake-only secrets from chain.
    oauth_payload_has_no_secrets — validate dispatcher payload omits credential fields.
    advance_discogs_oauth — multi-step consumer key → secret → verifier flow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.config.sections.skills_discogs import discogs_settings
from sevn.gateway.config_io.workspace_config_io import mutate_sevn_json
from sevn.gateway.menu.discogs_menu import (
    DISCOGS_CONSUMER_KEY_SECRET_ALIAS,
    DISCOGS_CONSUMER_SECRET_SECRET_ALIAS,
    DISCOGS_OAUTH_REQUEST_SECRET_SECRET_ALIAS,
    DISCOGS_OAUTH_REQUEST_TOKEN_SECRET_ALIAS,
    DISCOGS_OAUTH_TOKEN_SECRET_ALIAS,
    DISCOGS_OAUTH_TOKEN_SECRET_SECRET_ALIAS,
)
from sevn.integrations.discogs.oauth import DiscogsOAuthError, begin_oauth, complete_oauth
from sevn.onboarding.web_app import _set_nested
from sevn.security.secrets.factory import secrets_chain_from_workspace

if TYPE_CHECKING:
    from sevn.gateway.channel_router import IncomingMessage
    from sevn.gateway.commands.menu_form_handler import MenuFormHandler
    from sevn.security.secrets.chain import SecretsChain

_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "consumer_key",
        "consumer_secret",
        "request_token",
        "request_secret",
    },
)

__all__ = [
    "advance_discogs_oauth",
    "cleanup_discogs_oauth_interim_secrets",
    "oauth_payload_has_no_secrets",
]


def oauth_payload_has_no_secrets(payload: dict[str, Any]) -> bool:
    """Return whether *payload* omits Discogs credential fields.

    Dispatcher payloads must never carry consumer or request token material —
    those values live only in the workspace secrets chain.

    Args:
        payload (dict[str, Any]): Parsed ``dispatcher_state.payload_json``.

    Returns:
        bool: ``True`` when no forbidden keys are present.

    Examples:
        >>> oauth_payload_has_no_secrets({"step": "verifier"})
        True
        >>> oauth_payload_has_no_secrets({"consumer_key": "x"})
        False
    """
    return not any(key in payload for key in _FORBIDDEN_PAYLOAD_KEYS)


async def cleanup_discogs_oauth_interim_secrets(chain: SecretsChain) -> None:
    """Delete OAuth handshake interim secrets from the workspace chain.

    Args:
        chain (SecretsChain): Workspace secrets chain.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(cleanup_discogs_oauth_interim_secrets)
        True
    """
    for alias in (
        DISCOGS_OAUTH_REQUEST_TOKEN_SECRET_ALIAS,
        DISCOGS_OAUTH_REQUEST_SECRET_SECRET_ALIAS,
    ):
        try:
            await chain.delete(alias)
        except Exception:
            continue


async def advance_discogs_oauth(
    handler: MenuFormHandler,
    msg: IncomingMessage,
    *,
    token: str,
    step: str,
    text: str,
    payload: dict[str, Any],
) -> None:
    """Run the Discogs OAuth 1.0a setup wizard (consumer key → secret → verifier).

    Secrets are stored only in the workspace secrets chain — never in the
    dispatcher payload.

    Args:
        handler (MenuFormHandler): Active form handler instance.
        msg (IncomingMessage): Inbound chat text envelope.
        token (str): Active ``dispatcher_state`` token.
        step (str): Current step id.
        text (str): Operator reply text.
        payload (dict[str, Any]): Parsed wizard payload (step metadata only).

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(advance_discogs_oauth)
        True
    """
    if not handler._router._resolve_owner_flag(msg):
        handler._consume_token(token)
        await handler._send_chat(msg, "Owner only.")
        return

    user_agent = discogs_settings(handler._workspace).user_agent
    chain = secrets_chain_from_workspace(
        handler._content_root,
        handler._workspace.secrets_backend,
    )

    async def _secret_value(alias: str) -> str | None:
        value = await chain.get(alias)
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def _update_oauth_payload(next_step: str) -> None:
        clean_payload = {
            key: value for key, value in payload.items() if key not in _FORBIDDEN_PAYLOAD_KEYS
        }
        clean_payload["step"] = next_step
        assert oauth_payload_has_no_secrets(clean_payload)
        handler._update_payload(token, clean_payload)

    if step == "consumer_key":
        consumer_key = text.strip()
        if not consumer_key:
            await handler._send_chat(msg, "Consumer key cannot be empty.")
            return
        try:
            await chain.set(DISCOGS_CONSUMER_KEY_SECRET_ALIAS, consumer_key)
        except Exception:
            await handler._send_chat(msg, "Could not store consumer key — try again.")
            return
        _update_oauth_payload("consumer_secret")
        await handler._send_chat(
            msg,
            "Send your Discogs OAuth consumer secret (not shown again):",
        )
        return

    if step == "consumer_secret":
        consumer_secret = text.strip()
        if not consumer_secret:
            await handler._send_chat(msg, "Consumer secret cannot be empty.")
            return
        consumer_key = await _secret_value(DISCOGS_CONSUMER_KEY_SECRET_ALIAS) or ""
        if not consumer_key:
            handler._consume_token(token)
            await cleanup_discogs_oauth_interim_secrets(chain)
            await handler._send_chat(msg, "Wizard expired — start again from Discogs Setup.")
            return
        try:
            await chain.set(DISCOGS_CONSUMER_SECRET_SECRET_ALIAS, consumer_secret)
        except Exception:
            await handler._send_chat(msg, "Could not store consumer secret — try again.")
            return
        try:
            request_token, request_secret, authorize_url = begin_oauth(
                consumer_key,
                consumer_secret,
                user_agent,
            )
        except DiscogsOAuthError as exc:
            await handler._send_chat(msg, exc.message)
            return
        try:
            await chain.set(DISCOGS_OAUTH_REQUEST_TOKEN_SECRET_ALIAS, request_token)
            await chain.set(DISCOGS_OAUTH_REQUEST_SECRET_SECRET_ALIAS, request_secret)
        except Exception:
            await handler._send_chat(msg, "Could not store OAuth request token — try again.")
            return
        _update_oauth_payload("verifier")
        await handler._send_chat(
            msg,
            "Open this URL in a browser, authorize sevn, then paste the verifier code here.\n"
            "Privacy: the URL contains a one-time session token — open it only on a trusted "
            "device and avoid forwarding this chat message.\n"
            f"{authorize_url}",
        )
        return

    if step == "verifier":
        verifier = text.strip()
        if not verifier:
            await handler._send_chat(msg, "Verifier cannot be empty.")
            return
        consumer_key = await _secret_value(DISCOGS_CONSUMER_KEY_SECRET_ALIAS) or ""
        consumer_secret = await _secret_value(DISCOGS_CONSUMER_SECRET_SECRET_ALIAS) or ""
        request_token = await _secret_value(DISCOGS_OAUTH_REQUEST_TOKEN_SECRET_ALIAS) or ""
        request_secret = await _secret_value(DISCOGS_OAUTH_REQUEST_SECRET_SECRET_ALIAS) or ""
        if not all((consumer_key, consumer_secret, request_token, request_secret)):
            handler._consume_token(token)
            await cleanup_discogs_oauth_interim_secrets(chain)
            await handler._send_chat(msg, "Wizard expired — start again from Discogs Setup.")
            return
        try:
            access_token, access_secret = complete_oauth(
                consumer_key,
                consumer_secret,
                request_token,
                request_secret,
                verifier,
                user_agent,
            )
        except DiscogsOAuthError as exc:
            await handler._send_chat(msg, exc.message)
            return
        try:
            await chain.set(DISCOGS_OAUTH_TOKEN_SECRET_ALIAS, access_token)
            await chain.set(DISCOGS_OAUTH_TOKEN_SECRET_SECRET_ALIAS, access_secret)
            await cleanup_discogs_oauth_interim_secrets(chain)
        except Exception:
            await handler._send_chat(msg, "Could not store OAuth access token — try again.")
            return

        def _apply_discogs_oauth(doc: dict[str, Any]) -> None:
            _set_nested(doc, "skills.discogs.auth_method", "oauth")
            _set_nested(
                doc,
                "skills.discogs.consumer_key",
                f"${{SECRET:{DISCOGS_CONSUMER_KEY_SECRET_ALIAS}}}",
            )
            _set_nested(
                doc,
                "skills.discogs.consumer_secret",
                f"${{SECRET:{DISCOGS_CONSUMER_SECRET_SECRET_ALIAS}}}",
            )
            _set_nested(
                doc,
                "skills.discogs.oauth_token",
                f"${{SECRET:{DISCOGS_OAUTH_TOKEN_SECRET_ALIAS}}}",
            )
            _set_nested(
                doc,
                "skills.discogs.oauth_token_secret",
                f"${{SECRET:{DISCOGS_OAUTH_TOKEN_SECRET_SECRET_ALIAS}}}",
            )

        mutate_sevn_json(handler._sevn_json, _apply_discogs_oauth)
        handler._consume_token(token)
        await handler._refresh_section(msg, section="skills:discogs:setup", toast=None)
        await handler._send_chat(
            msg,
            "✅ OAuth tokens stored. Auth method set to oauth. Tap Test connection to verify.",
        )
        return
