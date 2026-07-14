"""``/platform`` slash command handler.

Module: sevn.gateway.commands.platform_commands
Depends: sevn.gateway.channel_router, sevn.gateway.runtime.platform_runtime

Exports:
    PlatformCommandHandler — ``/platform list|pause|resume`` for owners.
"""

from __future__ import annotations

from sevn.gateway.channel_router import ChannelRouter, IncomingMessage


class PlatformCommandHandler:
    """Owner-only runtime controls for registered channel adapters."""

    def __init__(self, *, router: ChannelRouter | None = None) -> None:
        """Bind optional router for platform runtime lookups.

        Args:
            router (ChannelRouter | None): Gateway router instance.

        Examples:
            >>> PlatformCommandHandler() is not None
            True
        """
        self._router = router

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return whether ``msg`` is a ``/platform`` command.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: Match verdict.

        Examples:
            >>> PlatformCommandHandler().matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/platform list"),
            ... )
            True
        """
        text = (msg.text or "").strip().lower()
        return text == "/platform" or text.startswith("/platform ")

    def handle(self, msg: IncomingMessage, *, is_owner: bool) -> str:
        """Execute ``/platform`` subcommands.

        Args:
            msg (IncomingMessage): Inbound slash command.
            is_owner (bool): Whether sender is workspace owner.

        Returns:
            str: User-visible reply text.

        Examples:
            >>> h = PlatformCommandHandler()
            >>> "owner" in h.handle(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/platform pause x"),
            ...     is_owner=False,
            ... ).lower()
            True
        """
        if not is_owner:
            return "Only the workspace owner may use `/platform` controls."
        text = (msg.text or "").strip()
        parts = text.split()
        sub = parts[1].lower() if len(parts) > 1 else "list"
        target = parts[2].strip().lower() if len(parts) > 2 else ""
        router = self._router
        if router is None:
            return "Platform runtime is unavailable."
        runtime = router.platform_runtime
        if sub == "list":
            rows = runtime.list_platforms()
            if not rows:
                return "No channel adapters registered."
            lines = ["Platforms:"]
            for row in rows:
                lines.append(
                    f"- {row.name}: {row.connection_state}"
                    + (f" ({row.last_error})" if row.last_error else "")
                )
            return "\n".join(lines)
        if sub == "pause":
            if not target:
                return "Usage: `/platform pause <name>`"
            if runtime.pause(target):
                return f"Paused `{target}`."
            return f"Unknown platform `{target}`."
        if sub == "resume":
            if not target:
                return "Usage: `/platform resume <name>`"
            if runtime.resume(target):
                return f"Resumed `{target}`."
            return f"Unknown platform `{target}`."
        return "Usage: `/platform list|pause|resume [name]`"


__all__ = ["PlatformCommandHandler"]
