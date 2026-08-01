"""Buzz channel adapter — relay webhook + outbound replies (#72, W31.3).

Module: sevn.channels.buzz
Depends: httpx, sevn.acp.buzz_config, sevn.gateway.channel_types

Exports:
    BuzzChannelAdapter — Buzz relay webhook adapter for gateway turns.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from sevn.acp.buzz_config import BuzzIdentity, resolve_buzz_identity
from sevn.channels._common import (
    PlatformChannelConfig,
    channel_blob,
    platform_config_from_workspace,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_types import ChannelAdapter, IncomingMessage, OutgoingMessage


class BuzzChannelAdapter(ChannelAdapter):
    """Buzz relay adapter: mentions in, replies via relay REST API."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig | None = None,
        content_root: str | None = None,
        trace: Any | None = None,
        sqlite_conn: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
        identity: BuzzIdentity | None = None,
    ) -> None:
        """Resolve Buzz identity and optional HTTP client (tests inject client).

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.
            content_root (str | None): Content root for secrets resolution.
            trace (Any | None): Optional trace sink (reserved).
            sqlite_conn (Any | None): Unused in this slice.
            http_client (httpx.AsyncClient | None): Shared async HTTP client.
            identity (BuzzIdentity | None): Pre-resolved identity (tests).

        Returns:
            None: Constructor.

        Examples:
            >>> BuzzChannelAdapter().name
            'buzz'
        """
        _ = trace, sqlite_conn
        self._workspace = workspace or WorkspaceConfig.minimal()
        self._content_root = content_root
        self._config = platform_config_from_workspace(self._workspace, "buzz")
        self._blob = channel_blob(self._workspace, "buzz")
        self._http = http_client
        self._identity = identity

    @classmethod
    def from_gateway_boot(cls, ctx: Any) -> BuzzChannelAdapter:
        """Build adapter during CW-2 channel boot hook.

        Args:
            ctx (Any): :class:`~sevn.gateway.boot_registry.BootContext` at runtime.

        Returns:
            BuzzChannelAdapter: Configured adapter instance.

        Examples:
            >>> import inspect
            >>> inspect.ismethod(BuzzChannelAdapter.from_gateway_boot)
            True
        """
        content_root = str(getattr(ctx, "content_root", "") or "")
        return cls(
            workspace=ctx.workspace,
            content_root=content_root or None,
            trace=ctx.trace,
            sqlite_conn=ctx.conn,
        )

    @property
    def name(self) -> str:
        """Return adapter key.

        Returns:
            str: ``buzz``.

        Examples:
            >>> BuzzChannelAdapter().name
            'buzz'
        """
        return "buzz"

    @property
    def config(self) -> PlatformChannelConfig:
        """Return resolved platform config.

        Returns:
            PlatformChannelConfig: Workspace slice.

        Examples:
            >>> BuzzChannelAdapter().config.enabled is None
            True
        """
        return self._config

    async def _resolved_identity(self) -> BuzzIdentity | None:
        """Resolve Buzz relay credentials from env or the secrets chain.

        Returns:
            BuzzIdentity | None: Resolved identity or ``None`` when incomplete.

        Examples:
            >>> import asyncio
            >>> asyncio.run(BuzzChannelAdapter()._resolved_identity()) is None
            True
        """
        if self._identity is not None:
            return self._identity
        if not self._content_root:
            return None
        return await resolve_buzz_identity(self._workspace, content_root=self._content_root)

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Parse Buzz relay mention / message webhook payloads.

        Args:
            payload (dict[str, Any]): Webhook JSON body.

        Returns:
            IncomingMessage | None: Normalised message or ``None``.

        Examples:
            >>> BuzzChannelAdapter().parse_webhook({"type": "ping"}) is None
            True
        """
        event_type = str(payload.get("type") or payload.get("event") or "").strip().lower()
        if event_type in {"ping", "health"}:
            return None
        body = payload.get("message") if isinstance(payload.get("message"), dict) else payload
        if not isinstance(body, dict):
            return None
        text = body.get("text") or body.get("content")
        if not isinstance(text, str) or not text.strip():
            return None
        author_raw = body.get("author")
        author: dict[str, Any] = author_raw if isinstance(author_raw, dict) else {}
        user_id = str(author.get("id") or body.get("user_id") or payload.get("user_id") or "")
        channel_obj = payload.get("channel")
        channel_from_obj = channel_obj.get("id") if isinstance(channel_obj, dict) else ""
        channel_id = str(
            body.get("channel_id") or payload.get("channel_id") or channel_from_obj or ""
        )
        if not user_id:
            return None
        metadata = {
            "channel_id": channel_id,
            "provider": "buzz",
            "chat_type": "group",
            "mention": bool(payload.get("mention") or payload.get("is_mention")),
        }
        return IncomingMessage(
            channel="buzz",
            user_id=user_id,
            text=text.strip(),
            raw=payload,
            metadata=metadata,
        )

    async def send(self, message: OutgoingMessage) -> list[str]:
        """Post a reply back into Buzz via the configured relay.

        Args:
            message (OutgoingMessage): Outbound envelope.

        Returns:
            list[str]: Provider message ids or empty on failure.

        Examples:
            >>> import asyncio
            >>> asyncio.run(
            ...     BuzzChannelAdapter().send(
            ...         OutgoingMessage(channel="buzz", user_id="u1", text="hi")
            ...     )
            ... )
            []
        """
        identity = await self._resolved_identity()
        if identity is None:
            logger.warning("buzz_send_skipped reason=missing_identity")
            return []
        metadata_base: dict[str, Any] = (
            message.metadata if isinstance(message.metadata, dict) else {}
        )
        channel_id = str(metadata_base.get("channel_id") or message.user_id)
        if not channel_id:
            return []
        url = f"{identity.relay_url}/api/v1/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bearer {identity.private_key}",
            "Content-Type": "application/json; charset=utf-8",
        }
        body = {"text": message.text[:8000], "reply_to_user_id": message.user_id}
        client = self._http or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http is None
        try:
            resp = await client.post(url, headers=headers, content=json.dumps(body))
            if resp.status_code >= 400:
                logger.warning("buzz_send_failed status={}", resp.status_code)
                return []
            data = resp.json() if resp.content else {}
            msg_id = str(data.get("id") or data.get("message_id") or "")
            return [msg_id] if msg_id else ["sent"]
        finally:
            if owns_client:
                await client.aclose()


__all__ = ["BuzzChannelAdapter"]
