"""Shared inline-query types, config, and auth helpers (I1; W6 boundary).

Module: sevn.gateway.telegram.telegram_inline_types
Depends: dataclasses, typing, sevn.config.defaults, sevn.config.sections.channels

Holds the inline value types and pure config/auth helpers consumed by both
``telegram_inline`` (router) and ``telegram_inline_sources`` (I2 builders). Living
here breaks the former circular import (finding-11): ``telegram_inline_sources``
imports these names from this module instead of late-importing from
``telegram_inline`` at module end.

Exports:
    InlineAuthContext — per-user agent-source gate (D8).
    InlineDispatchContext — auth + cache + source toggles for one query.
    resolve_inline_config — normalise ``TelegramInlineConfig`` with defaults.
    telegram_allowed_updates — Bot API ``allowed_updates`` list (D7).
    inline_user_may_use_agent_source — operator/allowed-user gate (D8).
    inline_source_cache_time — per-source ``cache_time`` for ``answerInlineQuery`` (D10).
    build_inline_dispatch_context — assemble dispatch context for one inline user.

Examples:
    >>> resolve_inline_config(None).enabled
    False
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sevn.config.defaults import (
    DEFAULT_TELEGRAM_INLINE_CACHE_TIME_AGENT,
    DEFAULT_TELEGRAM_INLINE_CACHE_TIME_STATIC,
    DEFAULT_TELEGRAM_INLINE_ENABLED,
    DEFAULT_TELEGRAM_INLINE_FEEDBACK,
)
from sevn.config.sections.channels import TelegramInlineConfig, TelegramInlineSourcesConfig

INLINE_MODULE_VERSION = "1.0.0-i3"

INLINE_BOTFATHER_SETUP_NOTE = (
    "Operator-deferred manual (D15): enable inline mode in BotFather with "
    "``/setinline``, optional ``/setinlinefeedback`` and ``/setinlinegeo``; "
    "see wave plan Final docs — not a CI gate."
)

DEFAULT_INLINE_PAGE_SIZE = 20

InlineSourceKind = Literal["agent", "second_brain", "printing_press", "artifacts"]

_BASE_ALLOWED_UPDATES: tuple[str, ...] = (
    "message",
    "edited_message",
    "callback_query",
)


@dataclass(frozen=True)
class InlineAuthContext:
    """Per-user inline auth snapshot (D8).

    Attributes:
        user_id: Requesting Telegram user id (string form).
        agent_source_allowed: ``True`` when source (a) agent answer may run.
        is_personal: Always ``True`` for ``answerInlineQuery`` (D8).
    """

    user_id: str
    agent_source_allowed: bool
    is_personal: bool = True


@dataclass(frozen=True)
class InlineDispatchContext:
    """Resolved inline dispatch knobs for one ``inline_query`` (I1; I3 consumes).

    Attributes:
        auth: Per-user auth gate.
        cache_time_agent: Short TTL for agent-answer results (seconds).
        cache_time_static: Longer TTL for static/printing-press results (seconds).
        sources_enabled: Per-source toggles from ``channels.telegram.inline.sources``.
    """

    auth: InlineAuthContext
    cache_time_agent: int
    cache_time_static: int
    sources_enabled: dict[str, bool]


def resolve_inline_config(cfg: TelegramInlineConfig | None) -> TelegramInlineConfig:
    """Return ``cfg`` or a default ``TelegramInlineConfig`` (``enabled=False``).

    Args:
        cfg (TelegramInlineConfig | None): Workspace ``channels.telegram.inline`` block.

    Returns:
        TelegramInlineConfig: Normalised inline config with defaults applied.

    Examples:
        >>> resolve_inline_config(None).enabled
        False
    """
    if cfg is None:
        return TelegramInlineConfig(
            enabled=DEFAULT_TELEGRAM_INLINE_ENABLED,
            feedback=DEFAULT_TELEGRAM_INLINE_FEEDBACK,
            cache_time_agent=DEFAULT_TELEGRAM_INLINE_CACHE_TIME_AGENT,
            cache_time_static=DEFAULT_TELEGRAM_INLINE_CACHE_TIME_STATIC,
        )
    return cfg


def telegram_allowed_updates(inline_cfg: TelegramInlineConfig | None) -> list[str]:
    """Build Bot API ``allowed_updates`` including inline types when enabled (D7).

    Args:
        inline_cfg (TelegramInlineConfig | None): ``channels.telegram.inline`` block.

    Returns:
        list[str]: Update type names for ``setWebhook`` / ``getUpdates``.

    Examples:
        >>> telegram_allowed_updates(None)
        ['message', 'edited_message', 'callback_query']
        >>> telegram_allowed_updates(
        ...     TelegramInlineConfig(enabled=True, feedback=True)
        ... )
        ['message', 'edited_message', 'callback_query', 'inline_query', 'chosen_inline_result']
    """
    updates = list(_BASE_ALLOWED_UPDATES)
    cfg = resolve_inline_config(inline_cfg)
    if cfg.enabled:
        updates.append("inline_query")
        if cfg.feedback:
            updates.append("chosen_inline_result")
    return updates


def inline_user_may_use_agent_source(
    user_id: str,
    *,
    owner_ids: frozenset[str],
    allowed_users: list[int],
) -> bool:
    """Return whether source (a) agent-answer results are allowed for *user_id* (D8).

    Agent-answer inline results are returned only to the workspace owner or
    ``channels.telegram.allowed_users`` entries.

    Args:
        user_id (str): Telegram user id as a string.
        owner_ids (frozenset[str]): Workspace owner id set from the router.
        allowed_users (list[int]): ``channels.telegram.allowed_users`` list.

    Returns:
        bool: ``True`` when the agent source may run for this inline user.

    Examples:
        >>> inline_user_may_use_agent_source("99", owner_ids=frozenset({"1"}), allowed_users=[2])
        False
        >>> inline_user_may_use_agent_source("1", owner_ids=frozenset({"1"}), allowed_users=[])
        True
        >>> inline_user_may_use_agent_source("2", owner_ids=frozenset(), allowed_users=[2])
        True
    """
    if user_id in owner_ids:
        return True
    try:
        uid = int(user_id)
    except ValueError:
        return False
    return uid in set(allowed_users)


def inline_source_cache_time(source: InlineSourceKind, cfg: TelegramInlineConfig) -> int:
    """Return ``cache_time`` seconds for one inline content source (D10).

    Args:
        source (InlineSourceKind): Content source identifier.
        cfg (TelegramInlineConfig): Resolved inline config.

    Returns:
        int: Seconds for ``answerInlineQuery.cache_time`` for that source class.

    Examples:
        >>> inline_source_cache_time("agent", TelegramInlineConfig())
        10
        >>> inline_source_cache_time("printing_press", TelegramInlineConfig())
        300
    """
    if source == "agent":
        return cfg.cache_time_agent
    return cfg.cache_time_static


def _sources_enabled_map(sources: TelegramInlineSourcesConfig) -> dict[str, bool]:
    """Return per-source enable flags from ``TelegramInlineSourcesConfig``.

    Args:
        sources (TelegramInlineSourcesConfig): Inline source toggles block.

    Returns:
        dict[str, bool]: Map of source name to enabled flag.

    Examples:
        >>> from sevn.config.sections.channels import TelegramInlineSourcesConfig
        >>> _sources_enabled_map(TelegramInlineSourcesConfig(agent=False))["agent"]
        False
    """
    return {
        "agent": bool(sources.agent),
        "second_brain": bool(sources.second_brain),
        "printing_press": bool(sources.printing_press),
        "artifacts": bool(sources.artifacts),
    }


def build_inline_dispatch_context(
    user_id: str,
    *,
    inline_cfg: TelegramInlineConfig,
    owner_ids: frozenset[str],
    allowed_users: list[int],
) -> InlineDispatchContext:
    """Assemble auth, cache, and source toggles for one inline query (I1).

    Args:
        user_id (str): Requesting Telegram user id.
        inline_cfg (TelegramInlineConfig): Resolved inline config.
        owner_ids (frozenset[str]): Workspace owner ids.
        allowed_users (list[int]): Telegram allowlist user ids.

    Returns:
        InlineDispatchContext: Context for I2/I3 result builders.

    Examples:
        >>> ctx = build_inline_dispatch_context(
        ...     "7",
        ...     inline_cfg=TelegramInlineConfig(enabled=True),
        ...     owner_ids=frozenset({"7"}),
        ...     allowed_users=[],
        ... )
        >>> ctx.auth.agent_source_allowed
        True
        >>> ctx.auth.is_personal
        True
    """
    agent_ok = inline_user_may_use_agent_source(
        user_id,
        owner_ids=owner_ids,
        allowed_users=allowed_users,
    )
    auth = InlineAuthContext(user_id=user_id, agent_source_allowed=agent_ok)
    sources = inline_cfg.sources
    return InlineDispatchContext(
        auth=auth,
        cache_time_agent=inline_cfg.cache_time_agent,
        cache_time_static=inline_cfg.cache_time_static,
        sources_enabled=_sources_enabled_map(sources),
    )


__all__ = [
    "DEFAULT_INLINE_PAGE_SIZE",
    "INLINE_BOTFATHER_SETUP_NOTE",
    "INLINE_MODULE_VERSION",
    "InlineAuthContext",
    "InlineDispatchContext",
    "InlineSourceKind",
    "build_inline_dispatch_context",
    "inline_source_cache_time",
    "inline_user_may_use_agent_source",
    "resolve_inline_config",
    "telegram_allowed_updates",
]
