"""Reddit karma loop config resolution (#74, W33).

Module: sevn.integrations.reddit_karma.config
Depends: dataclasses, typing, sevn.config.defaults

Exports:
    RedditKarmaConfig — effective loop settings from ``skills.reddit_karma_loop``.
    reddit_karma_loop_enabled — read ``enabled`` flag (default off).
    resolve_reddit_karma_config — merge defaults with workspace blob.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sevn.config.defaults import DEFAULT_REDDIT_KARMA_LOOP_ENABLED

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


@dataclass(frozen=True, slots=True)
class RedditKarmaConfig:
    """Effective Reddit karma loop settings."""

    enabled: bool = DEFAULT_REDDIT_KARMA_LOOP_ENABLED
    subreddits: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ("wiki", "second_brain")
    cron_expr: str = "0 9,15 * * *"
    max_comments_per_day: int = 5
    cooldown_seconds: int = 3600
    allow_links: bool = False
    ask_before_post: bool = False
    stop_on_mod_action: bool = True


def _reddit_karma_blob(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Return raw ``skills.reddit_karma_loop`` blob from workspace config.

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        dict[str, Any]: Skill config blob (possibly empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _reddit_karma_blob(WorkspaceConfig.minimal())
        {}
    """
    skills = getattr(workspace, "skills", None)
    raw = getattr(skills, "raw", None) if skills is not None else None
    if not isinstance(raw, dict):
        return {}
    blob = raw.get("reddit_karma_loop")
    return blob if isinstance(blob, dict) else {}


def reddit_karma_loop_enabled(workspace: WorkspaceConfig) -> bool:
    """Read ``skills.reddit_karma_loop.enabled`` (default off).

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        bool: Whether the loop skill is enabled.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> reddit_karma_loop_enabled(WorkspaceConfig.minimal())
        False
    """
    blob = _reddit_karma_blob(workspace)
    enabled = blob.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    return DEFAULT_REDDIT_KARMA_LOOP_ENABLED


def _normalize_str_list(raw: object) -> tuple[str, ...]:
    """Normalize a JSON string list, stripping ``r/`` prefixes.

    Args:
        raw (object): Config value that may be a list of strings.

    Returns:
        tuple[str, ...]: Cleaned string tuple.

    Examples:
        >>> _normalize_str_list(["r/python", "  rust  "])
        ('python', 'rust')
    """
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text:
            out.append(text.removeprefix("r/"))
    return tuple(out)


def resolve_reddit_karma_config(workspace: WorkspaceConfig) -> RedditKarmaConfig:
    """Resolve effective loop config from workspace ``skills.reddit_karma_loop``.

    Args:
        workspace (WorkspaceConfig): Bound workspace config.

    Returns:
        RedditKarmaConfig: Merged settings with defaults.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> cfg = resolve_reddit_karma_config(WorkspaceConfig.minimal())
        >>> cfg.enabled
        False
    """
    blob = _reddit_karma_blob(workspace)
    base = RedditKarmaConfig(enabled=reddit_karma_loop_enabled(workspace))
    subreddits = _normalize_str_list(blob.get("subreddits")) or base.subreddits
    topics = _normalize_str_list(blob.get("topics")) or base.topics
    source_paths = _normalize_str_list(blob.get("source_paths")) or base.source_paths
    cron_expr = str(blob.get("cron_expr") or base.cron_expr).strip() or base.cron_expr
    max_comments = blob.get("max_comments_per_day", base.max_comments_per_day)
    cooldown = blob.get("cooldown_seconds", base.cooldown_seconds)
    allow_links = blob.get("allow_links", base.allow_links)
    ask_before_post = blob.get("ask_before_post", base.ask_before_post)
    stop_on_mod = blob.get("stop_on_mod_action", base.stop_on_mod_action)
    return RedditKarmaConfig(
        enabled=reddit_karma_loop_enabled(workspace),
        subreddits=subreddits,
        topics=topics,
        source_paths=source_paths,
        cron_expr=cron_expr,
        max_comments_per_day=int(max_comments)
        if max_comments is not None
        else base.max_comments_per_day,
        cooldown_seconds=int(cooldown) if cooldown is not None else base.cooldown_seconds,
        allow_links=bool(allow_links),
        ask_before_post=bool(ask_before_post),
        stop_on_mod_action=bool(stop_on_mod),
    )


__all__ = [
    "RedditKarmaConfig",
    "reddit_karma_loop_enabled",
    "resolve_reddit_karma_config",
]
