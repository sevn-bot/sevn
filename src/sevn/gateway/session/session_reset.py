"""Per-channel session reset policies.

Module: sevn.gateway.session.session_reset
Depends: datetime, sevn.config.sections.channels

Exports:
    SessionResetPolicy — parsed reset policy for one channel.
    resolve_session_reset_policy — read policy from workspace config.
    session_should_reset — decide whether to rotate before next turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sevn.config.sections.channels import ChannelsWorkspaceSectionConfig, channel_extra_dict

ResetMode = Literal["daily", "idle", "both"]


@dataclass(frozen=True, slots=True)
class SessionResetPolicy:
    """Resolved session reset policy for one channel adapter."""

    mode: ResetMode | None
    idle_timeout_seconds: int

    @property
    def enabled(self) -> bool:
        """Return whether any reset rule is active.

        Returns:
            bool: ``True`` when ``mode`` is set.

        Examples:
            >>> SessionResetPolicy("daily", 3600).enabled
            True
            >>> SessionResetPolicy(None, 3600).enabled
            False
        """
        return self.mode is not None


def resolve_session_reset_policy(
    *,
    channel: str,
    workspace_channels: ChannelsWorkspaceSectionConfig | None,
) -> SessionResetPolicy:
    """Read ``session_reset_policy`` for one channel.

    Args:
        channel (str): Adapter name.
        workspace_channels (ChannelsWorkspaceSectionConfig | None): Parsed channels section.

    Returns:
        SessionResetPolicy: Effective policy with idle timeout default.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> p = resolve_session_reset_policy(
        ...     channel="telegram",
        ...     workspace_channels=WorkspaceConfig.minimal().channels,
        ... )
        >>> p.enabled
        False
    """
    extra = channel_extra_dict(workspace_channels, channel)
    raw_mode = extra.get("session_reset_policy")
    mode: ResetMode | None = None
    if isinstance(raw_mode, str):
        normalized = raw_mode.strip().lower()
        if normalized in ("daily", "idle", "both"):
            mode = normalized  # type: ignore[assignment]
    idle_raw = extra.get("session_idle_timeout_seconds", 86_400)
    idle_timeout = 86_400
    if isinstance(idle_raw, int) and idle_raw > 0:
        idle_timeout = idle_raw
    elif isinstance(idle_raw, float) and idle_raw > 0:
        idle_timeout = int(idle_raw)
    return SessionResetPolicy(mode=mode, idle_timeout_seconds=idle_timeout)


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse ISO-8601 timestamp strings used in session rows.

    Args:
        ts (str | None): Timestamp string.

    Returns:
        datetime | None: Parsed UTC datetime or ``None``.

    Examples:
        >>> _parse_iso("2026-06-15T12:00:00+00:00") is not None
        True
    """
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        normalized = ts.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def session_should_reset(
    *,
    policy: SessionResetPolicy,
    created_at: str | None,
    updated_at: str | None,
    now: datetime | None = None,
) -> bool:
    """Return whether an existing session should rotate before the next turn.

    Args:
        policy (SessionResetPolicy): Channel policy.
        created_at (str | None): Session ``created_at`` ISO timestamp.
        updated_at (str | None): Session ``updated_at`` ISO timestamp.
        now (datetime | None): Current time override for tests.

    Returns:
        bool: ``True`` when ``rotate_session`` should run.

    Examples:
        >>> from datetime import datetime, timedelta, UTC
        >>> policy = SessionResetPolicy("idle", 60)
        >>> old = (datetime.now(tz=UTC) - timedelta(seconds=120)).isoformat()
        >>> session_should_reset(policy=policy, created_at=old, updated_at=old)
        True
    """
    if not policy.enabled:
        return False
    clock = now or datetime.now(tz=UTC)
    created = _parse_iso(created_at)
    updated = _parse_iso(updated_at)
    daily_hit = False
    idle_hit = False
    if policy.mode in ("daily", "both") and created is not None:
        daily_hit = created.date() < clock.date()
    if policy.mode in ("idle", "both") and updated is not None:
        idle_hit = (clock - updated).total_seconds() >= policy.idle_timeout_seconds
    if policy.mode == "daily":
        return daily_hit
    if policy.mode == "idle":
        return idle_hit
    return daily_hit or idle_hit


__all__ = [
    "ResetMode",
    "SessionResetPolicy",
    "resolve_session_reset_policy",
    "session_should_reset",
]
