"""Stub channel adapter for Tier 2/3 platforms.

Module: sevn.channels.stub
Depends: sevn.gateway.channel_types

Exports:
    StubChannelAdapter — honest not-configured adapter for MC + doctor.
    make_stub_adapter_class — factory for entry-point classes.
"""

from __future__ import annotations

from typing import Any

from sevn.channels._common import PlatformChannelConfig, platform_config_from_workspace
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_types import ChannelAdapter, IncomingMessage, OutgoingMessage


class StubChannelAdapter(ChannelAdapter):
    """Placeholder adapter — registers in doctor/MC but does not connect."""

    channel_name: str = "stub"
    display_label: str = "Stub"

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig | None = None,
        trace: Any | None = None,
        sqlite_conn: Any | None = None,
    ) -> None:
        """Bind workspace-resolved config.

        Args:
            workspace (WorkspaceConfig | None): Parsed workspace config.
            trace (Any | None): Unused — signature parity with real adapters.
            sqlite_conn (Any | None): Unused — signature parity with real adapters.

        Returns:
            None: Constructor.

        Examples:
            >>> make_stub_adapter_class("matrix")().name
            'matrix'
        """
        _ = trace, sqlite_conn
        self._workspace = workspace or WorkspaceConfig.minimal()
        self._config = platform_config_from_workspace(self._workspace, self.channel_name)

    @property
    def name(self) -> str:
        """Return adapter key.

        Returns:
            str: Channel name.

        Examples:
            >>> make_stub_adapter_class("teams")().name
            'teams'
        """
        return self.channel_name

    @property
    def configured(self) -> bool:
        """Return whether required secrets/refs are present.

        Returns:
            bool: ``False`` for stub tier until operator wires transport.

        Examples:
            >>> make_stub_adapter_class("line")().configured
            False
        """
        return False

    @property
    def config(self) -> PlatformChannelConfig:
        """Return resolved platform config.

        Returns:
            PlatformChannelConfig: Workspace slice.

        Examples:
            >>> make_stub_adapter_class("ntfy")().config.enabled is None
            True
        """
        return self._config

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Ignore webhook traffic until adapter is fully implemented.

        Args:
            payload (dict[str, Any]): Provider webhook JSON.

        Returns:
            None: Always ignored for stub tier.

        Examples:
            >>> make_stub_adapter_class("qq")().parse_webhook({"event": "x"}) is None
            True
        """
        _ = payload
        return None

    async def send(self, message: OutgoingMessage) -> list[str]:
        """No-op send for unconfigured stub adapters.

        Args:
            message (OutgoingMessage): Outbound envelope.

        Returns:
            list[str]: Empty id list.

        Examples:
            >>> import asyncio
            >>> from sevn.gateway.channel_router import OutgoingMessage
            >>> asyncio.run(make_stub_adapter_class("yuanbao")().send(
            ...     OutgoingMessage(channel="yuanbao", user_id="1", text="hi")
            ... ))
            []
        """
        _ = message
        return []


def make_stub_adapter_class(
    channel_name: str, *, label: str | None = None
) -> type[StubChannelAdapter]:
    """Build a distinct adapter class for one ``sevn.channels`` entry point.

    Args:
        channel_name (str): Stable adapter key.
        label (str | None): Human label for logs.

    Returns:
        type[StubChannelAdapter]: Entry-point load target.

    Examples:
        >>> cls = make_stub_adapter_class("matrix")
        >>> cls().name
        'matrix'
    """
    title = label or channel_name.replace("_", " ").title()
    adapter_key = channel_name

    class _Adapter(StubChannelAdapter):
        channel_name = adapter_key
        display_label = title

    _Adapter.__name__ = f"{title.replace(' ', '')}ChannelAdapter"
    return _Adapter
