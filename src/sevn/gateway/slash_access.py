"""Per-platform slash command access control.

Module: sevn.gateway.slash_access
Depends: dataclasses, sevn.config.sections.channels

Exports:
    SlashAccessPolicy — resolved admin vs user slash policy for one scope.
    canonical_slash_command — normalize slash command name.
    is_admin_slash_command — detect admin-tier commands.
    policy_for_message — resolve policy for one inbound message.
    policy_from_channel_extra — build policy from channel config blob.
    slash_allowed_for_actor — combined admin + config tier gate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from sevn.config.sections.channels import ChannelsWorkspaceSectionConfig, channel_extra_dict

Scope = Literal["dm", "group"]

ADMIN_SLASH_COMMANDS: frozenset[str] = frozenset(
    {
        "/platform",
        "/config",
        "/logs",
        "/traces",
        "/model",
        "/voice",
        "/steer",
    }
)

_ALWAYS_ALLOWED_FOR_USERS: frozenset[str] = frozenset(
    {
        "help",
        "whoami",
        "status",
    }
)

_DM_CHAT_TYPES = frozenset({"dm", "direct", "private", ""})


@dataclass(frozen=True, slots=True)
class SlashAccessPolicy:
    """Resolved access policy for a single (channel, scope) pair."""

    enabled: bool
    admin_user_ids: frozenset[str]
    user_allowed_commands: frozenset[str]

    def is_admin(self, user_id: str | None) -> bool:
        """Return whether ``user_id`` is a slash admin for this scope.

        Args:
            user_id (str | None): Channel-native user id.

        Returns:
            bool: ``True`` when the user may run any slash command.

        Examples:
            >>> p = SlashAccessPolicy(True, frozenset({"1"}), frozenset())
            >>> p.is_admin("1")
            True
        """
        if not self.enabled:
            return True
        if not user_id:
            return False
        return str(user_id) in self.admin_user_ids

    def can_run(self, user_id: str | None, canonical_cmd: str) -> bool:
        """Return whether ``user_id`` may run ``canonical_cmd``.

        Args:
            user_id (str | None): Channel-native user id.
            canonical_cmd (str): Lowercase command without leading slash.

        Returns:
            bool: Authorization verdict.

        Examples:
            >>> p = SlashAccessPolicy(True, frozenset({"1"}), frozenset({"help"}))
            >>> p.can_run("2", "help")
            True
        """
        if not self.enabled:
            return True
        if self.is_admin(user_id):
            return True
        if not canonical_cmd:
            return False
        if canonical_cmd in _ALWAYS_ALLOWED_FOR_USERS:
            return True
        return canonical_cmd in self.user_allowed_commands


def is_admin_slash_command(text: str) -> bool:
    """Return ``True`` when text is an admin-tier slash command.

    Args:
        text (str): Inbound message text.

    Returns:
        bool: Admin tier match.

    Examples:
        >>> is_admin_slash_command("/platform list")
        True
        >>> is_admin_slash_command("/help")
        False
    """
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return False
    head = stripped.split(maxsplit=1)[0].lower()
    return head in ADMIN_SLASH_COMMANDS


def canonical_slash_command(text: str) -> str:
    """Return lowercase slash command name from inbound text.

    Args:
        text (str): Inbound message text.

    Returns:
        str: Command name without ``/``, or empty string when not a slash command.

    Examples:
        >>> canonical_slash_command("/Platform list")
        'platform'
    """
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return ""
    return raw.split(maxsplit=1)[0].lstrip("/").lower()


def _coerce_id_list(raw: Any) -> frozenset[str]:
    """Coerce config value into a frozenset of string ids.

    Args:
        raw (Any): Config list, comma string, or scalar.

    Returns:
        frozenset[str]: Normalised id set.

    Examples:
        >>> _coerce_id_list(["1", "2"]) == frozenset({"1", "2"})
        True
    """
    if raw is None:
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        items: Iterable[Any] = raw
    elif isinstance(raw, str):
        items = (segment for segment in raw.split(",") if segment.strip())
    else:
        items = (raw,)
    out: list[str] = []
    for item in items:
        value = str(item).strip()
        if value:
            out.append(value)
    return frozenset(out)


def _coerce_command_list(raw: Any) -> frozenset[str]:
    """Coerce config value into a frozenset of slash command names.

    Args:
        raw (Any): Config list, comma string, or scalar.

    Returns:
        frozenset[str]: Normalised command names without leading slash.

    Examples:
        >>> _coerce_command_list(["/help", "status"]) == frozenset({"help", "status"})
        True
    """
    if raw is None:
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        items: Iterable[Any] = raw
    elif isinstance(raw, str):
        items = (segment for segment in raw.split(",") if segment.strip())
    else:
        items = (raw,)
    out: list[str] = []
    for item in items:
        value = str(item).strip().lstrip("/").lower()
        if value:
            out.append(value)
    return frozenset(out)


def _scope_for_chat_type(chat_type: str | None) -> Scope:
    """Map adapter chat type metadata to slash scope.

    Args:
        chat_type (str | None): Adapter chat type string.

    Returns:
        Scope: ``dm`` or ``group``.

    Examples:
        >>> _scope_for_chat_type("private")
        'dm'
    """
    if chat_type and chat_type.lower() in _DM_CHAT_TYPES:
        return "dm"
    return "group"


def _keys_for_scope(scope: Scope) -> tuple[str, str]:
    """Return config key names for admin ids and user commands.

    Args:
        scope (Scope): ``dm`` or ``group``.

    Returns:
        tuple[str, str]: Admin-id key and user-command key.

    Examples:
        >>> _keys_for_scope("dm")
        ('allow_admin_from', 'user_allowed_commands')
    """
    if scope == "group":
        return ("group_allow_admin_from", "group_user_allowed_commands")
    return ("allow_admin_from", "user_allowed_commands")


def policy_from_channel_extra(extra: dict[str, Any], scope: Scope) -> SlashAccessPolicy:
    """Build slash policy from one channel config blob.

    Args:
        extra (dict[str, Any]): ``channels.<name>`` dict.
        scope (Scope): ``dm`` or ``group``.

    Returns:
        SlashAccessPolicy: Resolved policy.

    Examples:
        >>> policy_from_channel_extra({"allow_admin_from": ["1"]}, "dm").enabled
        True
    """
    admin_key, cmd_key = _keys_for_scope(scope)
    admin_ids = _coerce_id_list(extra.get(admin_key))
    cmds = _coerce_command_list(extra.get(cmd_key))
    if scope == "dm" and not cmds:
        cmds = _coerce_command_list(extra.get("group_user_allowed_commands"))
    enabled = bool(admin_ids)
    return SlashAccessPolicy(
        enabled=enabled,
        admin_user_ids=admin_ids,
        user_allowed_commands=cmds,
    )


def policy_for_message(
    *,
    channel: str,
    workspace_channels: ChannelsWorkspaceSectionConfig | None,
    user_id: str,
    chat_type: str | None,
) -> SlashAccessPolicy:
    """Resolve slash access policy for one inbound message.

    Args:
        channel (str): Adapter name.
        workspace_channels (ChannelsWorkspaceSectionConfig | None): Parsed channels section.
        user_id (str): Sender id.
        chat_type (str | None): Adapter chat type metadata.

    Returns:
        SlashAccessPolicy: Policy for slash gating at dispatch time.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> p = policy_for_message(
        ...     channel="telegram",
        ...     workspace_channels=WorkspaceConfig.minimal().channels,
        ...     user_id="1",
        ...     chat_type="private",
        ... )
        >>> p.enabled
        False
    """
    extra = channel_extra_dict(workspace_channels, channel)
    scope = _scope_for_chat_type(chat_type)
    return policy_from_channel_extra(extra, scope)


def slash_allowed_for_actor(text: str, *, is_owner: bool) -> bool:
    """Return whether a slash bypass is permitted for this actor (admin tier).

    Args:
        text (str): Inbound slash text.
        is_owner (bool): Workspace owner flag from router.

    Returns:
        bool: ``False`` when a non-owner attempts an admin-tier command.

    Examples:
        >>> slash_allowed_for_actor("/platform list", is_owner=False)
        False
        >>> slash_allowed_for_actor("/help", is_owner=False)
        True
    """
    return not (is_admin_slash_command(text) and not is_owner)


__all__ = [
    "ADMIN_SLASH_COMMANDS",
    "SlashAccessPolicy",
    "canonical_slash_command",
    "is_admin_slash_command",
    "policy_for_message",
    "policy_from_channel_extra",
    "slash_allowed_for_actor",
]
