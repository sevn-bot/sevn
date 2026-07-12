"""Slack channel adapter — Events API slice.

Module: sevn.channels.slack
Depends: httpx, sevn.gateway.channel_types

Exports:
    SlackChannelAdapter — Slack Events API webhook adapter.
"""

from __future__ import annotations

import json
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


class SlackChannelAdapter(ChannelAdapter):
    """Minimal Slack adapter using ``chat.postMessage`` for outbound sends."""

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
            >>> SlackChannelAdapter().name
            'slack'
        """
        _ = trace, sqlite_conn
        self._workspace = workspace or WorkspaceConfig.minimal()
        self._config = platform_config_from_workspace(self._workspace, "slack")
        self._blob = channel_blob(self._workspace, "slack")
        self._http = http_client

    @classmethod
    def from_gateway_boot(cls, ctx: Any) -> SlackChannelAdapter:
        """Build adapter during CW-2 channel boot hook.

        Args:
            ctx (Any): :class:`~sevn.gateway.boot_registry.BootContext` at runtime.

        Returns:
            SlackChannelAdapter: Configured adapter instance.

        Examples:
            >>> import inspect
            >>> inspect.ismethod(SlackChannelAdapter.from_gateway_boot)
            True
        """
        return cls(workspace=ctx.workspace, trace=ctx.trace, sqlite_conn=ctx.conn)

    @property
    def name(self) -> str:
        """Return adapter key.

        Returns:
            str: ``slack``.

        Examples:
            >>> SlackChannelAdapter().name
            'slack'
        """
        return "slack"

    @property
    def config(self) -> PlatformChannelConfig:
        """Return resolved platform config.

        Returns:
            PlatformChannelConfig: Workspace slice.

        Examples:
            >>> SlackChannelAdapter().config.enabled is None
            True
        """
        return self._config

    def _bot_token(self) -> str:
        """Return configured bot token or secret ref placeholder.

        Returns:
            str: Inline token or ref string (refs resolved at send time elsewhere).

        Examples:
            >>> SlackChannelAdapter()._bot_token()
            ''
        """
        token = str(self._blob.get("bot_token") or "").strip()
        if token:
            return token
        return str(self._config.bot_token_ref or self._blob.get("bot_token_ref") or "").strip()

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Parse Slack Events API ``event_callback`` payloads.

        Args:
            payload (dict[str, Any]): Webhook JSON body.

        Returns:
            IncomingMessage | None: Normalised message or ``None``.

        Examples:
            >>> SlackChannelAdapter().parse_webhook({"type": "url_verification"}) is None
            True
        """
        if payload.get("type") != "event_callback":
            return None
        event = payload.get("event")
        if not isinstance(event, dict):
            return None
        if event.get("type") != "message":
            return None
        if event.get("bot_id") or event.get("subtype"):
            return None
        text = event.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        user_id = str(event.get("user") or "")
        channel_id = str(event.get("channel") or "")
        if not user_id:
            return None
        metadata = {"channel_id": channel_id, "provider": "slack", "chat_type": "group"}
        return IncomingMessage(
            channel="slack",
            user_id=user_id,
            text=text.strip(),
            metadata=metadata,
        )

    async def send(self, message: OutgoingMessage) -> list[str]:
        """Post a message via Slack Web API.

        Args:
            message (OutgoingMessage): Outbound envelope.

        Returns:
            list[str]: Provider message ids (ts) or empty on failure.

        Examples:
            >>> import asyncio
            >>> asyncio.run(SlackChannelAdapter().send(
            ...     OutgoingMessage(channel="slack", user_id="U1", text="hi")
            ... ))
            []
        """
        channel_id = str((message.metadata or {}).get("channel_id") or message.user_id)
        token = self._bot_token()
        if not token or not channel_id:
            return []
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        body = {"channel": channel_id, "text": message.text[:4000]}
        client = self._http or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http is None
        try:
            resp = await client.post(url, headers=headers, content=json.dumps(body))
            data = resp.json()
            if not data.get("ok"):
                logger.warning("slack_send_failed error={}", data.get("error"))
                return []
            ts = str(data.get("ts") or "")
            return [ts] if ts else []
        finally:
            if owns_client:
                await client.aclose()
