"""Turn-scoped system prompt overlays for tier-B assembly (#86 / W9).

Module: sevn.agent.prompt_overlays
Depends: sevn.config.channel_overrides

Exports:
    PromptOverlaySource — which level supplied the prompt overlay.
    TurnPromptOverlays — resolved overlay text + provenance for a turn.
    resolve_turn_prompt_overlays — channel/topic prompt lookup for one turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sevn.config.channel_overrides import resolve_channel_system_prompt_override


class PromptOverlaySource(StrEnum):
    """Provenance label for a turn-scoped system prompt overlay."""

    topic = "topic"
    channel = "channel"
    routing_profile = "routing_profile"
    metadata = "metadata"
    none = "none"


@dataclass(frozen=True)
class TurnPromptOverlays:
    """Resolved tier-B prompt overlay for one turn."""

    system_prompt: str | None
    source: PromptOverlaySource


def resolve_turn_prompt_overlays(
    cfg: object,
    *,
    channel: str = "",
    scope_key: str | None = None,
    metadata_topic_prompt: str | None = None,
    routing_profile_prompt: str | None = None,
) -> TurnPromptOverlays:
    """Resolve channel/topic system prompt overlay for tier-B assembly.

    Topic-level prompts beat channel-level prompts. Inbound metadata topic
    prompts beat config lookup for the same topic (**W9.5**). Routing profile
    prompts apply when channel/topic overlays are absent (**W12**).

    Args:
        cfg (object): Parsed workspace settings.
        channel (str): Active channel adapter name.
        scope_key (str | None): Session scope key for topic resolution.
        metadata_topic_prompt (str | None): Topic prompt from inbound metadata.
        routing_profile_prompt (str | None): Named routing profile prompt (**W12**).

    Returns:
        TurnPromptOverlays: Overlay text and provenance; absent keys ⇒ ``none``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = WorkspaceConfig.minimal(
        ...     channels={"telegram": {"system_prompt": "CHANNEL"}},
        ... )
        >>> o = resolve_turn_prompt_overlays(cfg, channel="telegram")
        >>> o.system_prompt
        'CHANNEL'
        >>> o.source
        <PromptOverlaySource.channel: 'channel'>
    """
    from sevn.config.channel_overrides import topic_id_from_scope_key

    if metadata_topic_prompt and metadata_topic_prompt.strip():
        return TurnPromptOverlays(
            system_prompt=metadata_topic_prompt.strip(),
            source=PromptOverlaySource.metadata,
        )
    topic_id = topic_id_from_scope_key(scope_key)
    channels = getattr(cfg, "channels", None)
    from sevn.config.sections.channels import channel_extra_dict

    extra = channel_extra_dict(channels, channel.strip()) if channel.strip() else {}
    if topic_id is not None and extra:
        topics = extra.get("topics")
        if isinstance(topics, dict):
            raw = topics.get(str(topic_id)) if str(topic_id) in topics else topics.get(topic_id)
            if isinstance(raw, dict):
                prompt = raw.get("system_prompt")
                if isinstance(prompt, str) and prompt.strip():
                    return TurnPromptOverlays(
                        system_prompt=prompt.strip(),
                        source=PromptOverlaySource.topic,
                    )
    channel_prompt = resolve_channel_system_prompt_override(
        cfg,
        channel=channel,
        scope_key=scope_key,
    )
    if channel_prompt is not None:
        return TurnPromptOverlays(
            system_prompt=channel_prompt,
            source=PromptOverlaySource.channel,
        )
    profile_prompt = (
        routing_profile_prompt.strip()
        if isinstance(routing_profile_prompt, str) and routing_profile_prompt.strip()
        else None
    )
    if profile_prompt is not None:
        return TurnPromptOverlays(
            system_prompt=profile_prompt,
            source=PromptOverlaySource.routing_profile,
        )
    return TurnPromptOverlays(system_prompt=None, source=PromptOverlaySource.none)
