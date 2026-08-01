"""Turn-scoped channel and topic overrides from ``channels.<name>.*``.

Module: sevn.config.channel_overrides
Depends: sevn.config.sections.channels

Exports:
    topic_id_from_scope_key — parse forum/topic id from a session scope key.
    resolve_channel_model_override — channel/topic model overlay (absent ⇒ None).
    resolve_channel_system_prompt_override — channel/topic prompt overlay.
    resolve_channel_reasoning_effort_override — channel/topic reasoning effort overlay.
"""

from __future__ import annotations

from typing import Any

from sevn.config.sections.channels import channel_extra_dict


def topic_id_from_scope_key(scope_key: str | None) -> int | None:
    """Extract a Telegram forum topic id from a gateway scope key when present.

    Supports test keys ``forum:<chat>:<topic>`` and production
    ``telegram:<chat>:topic:<topic>``.

    Args:
        scope_key (str | None): Session scope override or default scope key.

    Returns:
        int | None: Topic id when the key names a forum topic thread.

    Examples:
        >>> topic_id_from_scope_key("forum:100:42")
        42
        >>> topic_id_from_scope_key("telegram:100:topic:42")
        42
        >>> topic_id_from_scope_key("telegram:100:general") is None
        True
    """
    if not scope_key or not scope_key.strip():
        return None
    parts = scope_key.strip().split(":")
    if len(parts) == 3 and parts[0] == "forum":
        try:
            return int(parts[2])
        except ValueError:
            return None
    if len(parts) == 4 and parts[0] == "telegram" and parts[2] == "topic":
        try:
            return int(parts[3])
        except ValueError:
            return None
    return None


def _topic_entry(extra: dict[str, Any], topic_id: int) -> dict[str, Any]:
    """Return one topic config dict from a channel ``topics`` map.

    Args:
        extra (dict[str, Any]): Channel config blob.
        topic_id (int): Forum topic id.

    Returns:
        dict[str, Any]: Topic entry or empty dict when missing.

    Examples:
        >>> _topic_entry({"topics": {"1": {"model": "openai/gpt-4o"}}}, 1)
        {'model': 'openai/gpt-4o'}
    """
    topics = extra.get("topics")
    if not isinstance(topics, dict):
        return {}
    raw = topics.get(str(topic_id))
    if raw is None:
        raw = topics.get(topic_id)
    return dict(raw) if isinstance(raw, dict) else {}


def _non_empty_str(value: object) -> str | None:
    """Return stripped text when ``value`` is a non-empty string.

    Args:
        value (object): Candidate config value.

    Returns:
        str | None: Stripped string or ``None``.

    Examples:
        >>> _non_empty_str("  m ")
        'm'
        >>> _non_empty_str("") is None
        True
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_channel_model_override(
    cfg: object,
    *,
    channel: str,
    scope_key: str | None,
) -> str | None:
    """Return a channel- or topic-level model id when configured.

    Args:
        cfg (object): Parsed workspace settings.
        channel (str): Active channel adapter name.
        scope_key (str | None): Session scope key for topic resolution.

    Returns:
        str | None: Override model id, or ``None`` when unset (**D9** default-off).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     channels={"telegram": {"model": "openai/gpt-4.1"}},
        ... )
        >>> resolve_channel_model_override(cfg, channel="telegram", scope_key=None)
        'openai/gpt-4.1'
    """
    if not channel or not channel.strip():
        return None
    channels = getattr(cfg, "channels", None)
    extra = channel_extra_dict(channels, channel.strip())
    if not extra:
        return None
    topic_id = topic_id_from_scope_key(scope_key)
    if topic_id is not None:
        topic_model = _non_empty_str(_topic_entry(extra, topic_id).get("model"))
        if topic_model is not None:
            return topic_model
    return _non_empty_str(extra.get("model"))


def resolve_channel_system_prompt_override(
    cfg: object,
    *,
    channel: str,
    scope_key: str | None,
    metadata_prompt: str | None = None,
) -> str | None:
    """Return a channel- or topic-level system prompt when configured.

    ``metadata_prompt`` (from inbound adapter metadata) wins over config lookup
    for the same topic so runtime ``TopicConfig`` stays authoritative.

    Args:
        cfg (object): Parsed workspace settings.
        channel (str): Active channel adapter name.
        scope_key (str | None): Session scope key for topic resolution.
        metadata_prompt (str | None): Optional topic prompt from inbound metadata.

    Returns:
        str | None: Override prompt text, or ``None`` when unset.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     channels={"telegram": {"system_prompt": "Be terse."}},
        ... )
        >>> resolve_channel_system_prompt_override(cfg, channel="telegram", scope_key=None)
        'Be terse.'
    """
    meta = _non_empty_str(metadata_prompt)
    if meta is not None:
        return meta
    if not channel or not channel.strip():
        return None
    channels = getattr(cfg, "channels", None)
    extra = channel_extra_dict(channels, channel.strip())
    if not extra:
        return None
    topic_id = topic_id_from_scope_key(scope_key)
    if topic_id is not None:
        topic_prompt = _non_empty_str(_topic_entry(extra, topic_id).get("system_prompt"))
        if topic_prompt is not None:
            return topic_prompt
    return _non_empty_str(extra.get("system_prompt"))


def resolve_channel_reasoning_effort_override(
    cfg: object,
    *,
    channel: str,
    scope_key: str | None,
) -> str | None:
    """Return a channel- or topic-level reasoning effort when configured.

    Args:
        cfg (object): Parsed workspace settings.
        channel (str): Active channel adapter name.
        scope_key (str | None): Session scope key for topic resolution.

    Returns:
        str | None: Override effort label, or ``None`` when unset (**D9** default-off).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     channels={"telegram": {"reasoning_effort": "high"}},
        ... )
        >>> resolve_channel_reasoning_effort_override(cfg, channel="telegram", scope_key=None)
        'high'
    """
    if not channel or not channel.strip():
        return None
    channels = getattr(cfg, "channels", None)
    extra = channel_extra_dict(channels, channel.strip())
    if not extra:
        return None
    topic_id = topic_id_from_scope_key(scope_key)
    if topic_id is not None:
        topic_effort = _non_empty_str(_topic_entry(extra, topic_id).get("reasoning_effort"))
        if topic_effort is not None:
            return topic_effort
    return _non_empty_str(extra.get("reasoning_effort"))
