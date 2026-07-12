"""Discord channel adapter — webhook-first slice.

Module: sevn.channels.discord
Depends: httpx, sevn.gateway.channel_types

Exports:
    DiscordChannelAdapter — Discord Bot API webhook adapter.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from sevn.channels._common import (
    PlatformChannelConfig,
    channel_blob,
    platform_config_from_workspace,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_types import ChannelAdapter, IncomingMessage, OutgoingMessage


class DiscordChannelAdapter(ChannelAdapter):
    """Minimal Discord adapter using Bot REST API for outbound sends."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig | None = None,
        trace: Any | None = None,
        sqlite_conn: Any | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Resolve config and optional HTTP client (tests inject client).

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.
            trace (Any | None): Optional trace sink (reserved).
            sqlite_conn (Any | None): Unused in this slice.
            http_client (httpx.AsyncClient | None): Shared async HTTP client.

        Returns:
            None: Constructor.

        Examples:
            >>> DiscordChannelAdapter().name
            'discord'
        """
        _ = trace, sqlite_conn
        self._workspace = workspace or WorkspaceConfig.minimal()
        self._config = platform_config_from_workspace(self._workspace, "discord")
        self._blob = channel_blob(self._workspace, "discord")
        self._http = http_client

    @classmethod
    def from_gateway_boot(cls, ctx: Any) -> DiscordChannelAdapter:
        """Build adapter during CW-2 channel boot hook.

        Args:
            ctx (Any): :class:`~sevn.gateway.boot_registry.BootContext` at runtime.

        Returns:
            DiscordChannelAdapter: Configured adapter instance.

        Examples:
            >>> import inspect
            >>> inspect.ismethod(DiscordChannelAdapter.from_gateway_boot)
            True
        """
        return cls(workspace=ctx.workspace, trace=ctx.trace, sqlite_conn=ctx.conn)

    @property
    def name(self) -> str:
        """Return adapter key.

        Returns:
            str: ``discord``.

        Examples:
            >>> DiscordChannelAdapter().name
            'discord'
        """
        return "discord"

    @property
    def config(self) -> PlatformChannelConfig:
        """Return resolved platform config.

        Returns:
            PlatformChannelConfig: Workspace slice.

        Examples:
            >>> DiscordChannelAdapter().config.enabled is None
            True
        """
        return self._config

    def _bot_token(self) -> str:
        """Return configured bot token or secret ref placeholder.

        Returns:
            str: Inline token or ref string (refs resolved at send time elsewhere).

        Examples:
            >>> DiscordChannelAdapter()._bot_token()
            ''
        """
        token = str(self._blob.get("bot_token") or "").strip()
        if token:
            return token
        return str(self._config.bot_token_ref or self._blob.get("bot_token_ref") or "").strip()

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Parse Discord ``MESSAGE_CREATE`` or interaction payload.

        Args:
            payload (dict[str, Any]): Webhook JSON body.

        Returns:
            IncomingMessage | None: Normalised message or ``None``.

        Examples:
            >>> DiscordChannelAdapter().parse_webhook({"type": 1}) is None
            True
        """
        if payload.get("type") == 1:
            return None
        event = payload.get("d") if isinstance(payload.get("d"), dict) else payload
        if not isinstance(event, dict):
            return None
        author = event.get("author")
        if not isinstance(author, dict):
            return None
        content = event.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        user_id = str(author.get("id") or "")
        channel_id = str(event.get("channel_id") or "")
        if not user_id:
            return None
        metadata = {"channel_id": channel_id, "provider": "discord", "chat_type": "group"}
        return IncomingMessage(
            channel="discord",
            user_id=user_id,
            text=content.strip(),
            metadata=metadata,
        )

    async def send(self, message: OutgoingMessage) -> list[str]:
        """Post a message via Discord REST API.

        Args:
            message (OutgoingMessage): Outbound envelope.

        Returns:
            list[str]: Provider message ids (may be empty on failure).

        Examples:
            >>> import asyncio
            >>> asyncio.run(DiscordChannelAdapter().send(
            ...     OutgoingMessage(channel="discord", user_id="1", text="hi")
            ... ))
            []
        """
        channel_id = str((message.metadata or {}).get("channel_id") or message.user_id)
        token = self._bot_token()
        if not token or not channel_id:
            return []
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
        body = {"content": message.text[:2000]}
        client = self._http or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http is None
        try:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                logger.warning(
                    "discord_send_failed status={} body={}",
                    resp.status_code,
                    resp.text[:200],
                )
                return []
            data = resp.json()
            mid = str(data.get("id") or "")
            return [mid] if mid else []
        finally:
            if owns_client:
                await client.aclose()
