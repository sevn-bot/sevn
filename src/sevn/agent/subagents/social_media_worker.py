"""Execute ``social_media_manager`` specialist tasks (TwexAPI + toolkit surface).

Module: sevn.agent.subagents.social_media_worker
Depends: sevn.agent.subagents.specialists, sevn.integrations.twexapi,
    sevn.config.loader

Exports:
    SOCIAL_MEDIA_MANAGER_* — specialist id and default assigned skills/tools.
    SocialMediaTask — parsed task payload.
    parse_social_media_task — task-string → :class:`SocialMediaTask`.
    require_social_media_manager — resolve configured specialist or raise.
    assigned_skills_for — effective skills list for a specialist entry.
    assigned_tools_for — effective tools list for a specialist entry.
    execute_social_media_manager_task — run one social-media job.
    execute_social_media_manager_for_context — :class:`ToolContext` wrapper.

Examples:
    >>> from sevn.agent.subagents.social_media_worker import SOCIAL_MEDIA_MANAGER_SPECIALIST
    >>> SOCIAL_MEDIA_MANAGER_SPECIALIST
    'social_media_manager'
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.agent.subagents.specialists import resolve_specialist
from sevn.config.loader import load_workspace
from sevn.integrations.twexapi.client import TWEXAPI_OPS, TwexApiClient, TwexApiError
from sevn.integrations.twexapi.config import (
    load_twexapi_settings,
    resolve_twexapi_api_key,
)

if TYPE_CHECKING:
    from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
    from sevn.tools.context import ToolContext

SOCIAL_MEDIA_MANAGER_SPECIALIST = "social_media_manager"
SOCIAL_MEDIA_MANAGER_SKILL = "social_media_manager"
SOCIAL_MEDIA_MANAGER_UNCONFIGURED = (
    "social media management requires subagents.specialists.social_media_manager — "
    "configure the specialist (see infra/sevn.schema.json D8 example)"
)

# Existing core skills the Social Media Manager should have in its toolkit.
DEFAULT_SOCIAL_MEDIA_MANAGER_SKILLS: tuple[str, ...] = (
    "social_media_manager",
    "x-use",
    "facebook-use",
    "linkedin-use",
    "playwright-browser",
    "browser-harness",
    "last30days",
    "yt-dlp",
    "media_generation",
    "scheduling",
)

# Existing core tools — includes sevn's native CDP ``browser`` automator.
DEFAULT_SOCIAL_MEDIA_MANAGER_TOOLS: tuple[str, ...] = (
    "browser",
    "get_page_content",
    "web_fetch",
    "web_search",
    "serp",
    "load_skill",
    "run_skill_script",
    "send_file",
    "message",
)

SocialMedium = Literal["twexapi", "browser", "capabilities"]

__all__ = [
    "DEFAULT_SOCIAL_MEDIA_MANAGER_SKILLS",
    "DEFAULT_SOCIAL_MEDIA_MANAGER_TOOLS",
    "SOCIAL_MEDIA_MANAGER_SKILL",
    "SOCIAL_MEDIA_MANAGER_SPECIALIST",
    "SOCIAL_MEDIA_MANAGER_UNCONFIGURED",
    "SocialMediaTask",
    "assigned_skills_for",
    "assigned_tools_for",
    "execute_social_media_manager_for_context",
    "execute_social_media_manager_task",
    "parse_social_media_task",
    "require_social_media_manager",
]


@dataclass(frozen=True, slots=True)
class SocialMediaTask:
    """One social-media specialist request parsed from a spawn/skill task string."""

    medium: SocialMedium
    op: str
    params: dict[str, Any]
    body: dict[str, Any]
    path_params: dict[str, str]
    site: str | None = None
    query: str | None = None
    url: str | None = None
    text: str | None = None


def require_social_media_manager(
    cfg: SubAgentsWorkspaceConfig | None,
) -> SpecialistConfig:
    """Return the configured ``social_media_manager`` specialist entry.

    Args:
        cfg (SubAgentsWorkspaceConfig | None): Parsed ``subagents`` subtree.

    Returns:
        SpecialistConfig: Configured specialist.

    Raises:
        TwexApiError: When the specialist is not configured (shared error type
            for specialist misconfiguration on this worker).

    Examples:
        >>> require_social_media_manager(None)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        TwexApiError
    """
    entry = resolve_specialist(cfg, SOCIAL_MEDIA_MANAGER_SPECIALIST)
    if entry is None:
        raise TwexApiError(SOCIAL_MEDIA_MANAGER_UNCONFIGURED)
    return entry


def assigned_skills_for(specialist: SpecialistConfig) -> list[str]:
    """Return the effective skills list for a specialist entry.

    Prefers explicit ``specialist.skills``; falls back to the Social Media Manager
    default toolkit when empty and the entry is that specialist (via ``skill``
    field or caller context).

    Args:
        specialist (SpecialistConfig): Specialist entry.

    Returns:
        list[str]: Ordered skill ids.

    Examples:
        >>> from sevn.config.sections.subagents import SpecialistConfig
        >>> assigned_skills_for(SpecialistConfig(model="m", provider="p", skills=["x-use"]))
        ['x-use']
    """
    explicit = [s.strip() for s in specialist.skills if s.strip()]
    if explicit:
        return explicit
    if (specialist.skill or "").strip() == SOCIAL_MEDIA_MANAGER_SKILL:
        return list(DEFAULT_SOCIAL_MEDIA_MANAGER_SKILLS)
    return []


def assigned_tools_for(specialist: SpecialistConfig) -> list[str]:
    """Return the effective tools list for a specialist entry.

    Args:
        specialist (SpecialistConfig): Specialist entry.

    Returns:
        list[str]: Ordered tool ids.

    Examples:
        >>> from sevn.config.sections.subagents import SpecialistConfig
        >>> assigned_tools_for(SpecialistConfig(model="m", provider="p", tools=["browser"]))
        ['browser']
    """
    explicit = [t.strip() for t in specialist.tools if t.strip()]
    if explicit:
        return explicit
    if (specialist.skill or "").strip() == SOCIAL_MEDIA_MANAGER_SKILL:
        return list(DEFAULT_SOCIAL_MEDIA_MANAGER_TOOLS)
    return []


def parse_social_media_task(task: str) -> SocialMediaTask:
    """Parse a social-media task string (JSON or ``medium:op`` shorthand).

    Args:
        task (str): Spawn/skill task text.

    Returns:
        SocialMediaTask: Parsed request.

    Raises:
        ValueError: When the task is empty or malformed.

    Examples:
        >>> parse_social_media_task('{"medium":"capabilities"}').medium
        'capabilities'
        >>> parse_social_media_task("twexapi:search").op
        'search'
    """
    text = task.strip()
    if not text:
        msg = "social media task must be non-empty"
        raise ValueError(msg)
    if text.startswith("{"):
        raw = json.loads(text)
        if not isinstance(raw, dict):
            msg = "social media task JSON must be an object"
            raise ValueError(msg)
        medium = str(raw.get("medium") or "twexapi").strip().lower()
        if medium not in ("twexapi", "browser", "capabilities"):
            msg = "medium must be twexapi|browser|capabilities"
            raise ValueError(msg)
        path_params_raw = raw.get("path_params") or {}
        if not isinstance(path_params_raw, dict):
            msg = "path_params must be an object"
            raise ValueError(msg)
        params_raw = raw.get("params") or {}
        body_raw = raw.get("body") or raw.get("json") or {}
        if not isinstance(params_raw, dict) or not isinstance(body_raw, dict):
            msg = "params/body must be objects"
            raise ValueError(msg)
        return SocialMediaTask(
            medium=medium,  # type: ignore[arg-type]
            op=str(raw.get("op") or raw.get("action") or "").strip().lower(),
            params={str(k): v for k, v in params_raw.items()},
            body={str(k): v for k, v in body_raw.items()},
            path_params={str(k): str(v) for k, v in path_params_raw.items()},
            site=(str(raw["site"]).strip() if raw.get("site") else None),
            query=(str(raw["query"]).strip() if raw.get("query") else None),
            url=(str(raw["url"]).strip() if raw.get("url") else None),
            text=(str(raw["text"]).strip() if raw.get("text") else None),
        )
    if ":" in text:
        head, _, tail = text.partition(":")
        medium = head.strip().lower()
        op = tail.strip().lower()
        if medium in ("twexapi", "browser", "capabilities"):
            return SocialMediaTask(
                medium=medium,  # type: ignore[arg-type]
                op=op if medium != "capabilities" else "list",
                params={},
                body={},
                path_params={},
            )
    bare = text.lower()
    if bare in ("twexapi", "browser", "capabilities"):
        return SocialMediaTask(
            medium=bare,  # type: ignore[arg-type]
            op="list" if bare == "capabilities" else "",
            params={},
            body={},
            path_params={},
        )
    msg = "social media task must be JSON or medium:op (twexapi|browser|capabilities)"
    raise ValueError(msg)


def _browser_plan(task: SocialMediaTask) -> dict[str, Any]:
    """Build a browser-medium plan that uses sevn's CDP ``browser`` tool.

    Args:
        task (SocialMediaTask): Parsed browser request.

    Returns:
        dict[str, Any]: Plan describing the native CDP automator invocation.

    Examples:
        >>> plan = _browser_plan(SocialMediaTask("browser", "search", {}, {}, {}, site="x", query="ai"))
        >>> plan["tool"]
        'browser'
    """
    op = task.op or "search"
    site = task.site or "x"
    return {
        "medium": "browser",
        "tool": "browser",
        "engine": "cdp",
        "action": "social",
        "op": op,
        "site": site,
        "query": task.query,
        "url": task.url,
        "body": task.text,
        "skills": ["playwright-browser", "browser-harness", "x-use", "facebook-use", "linkedin-use"],
        "hint": (
            "Invoke the native `browser` tool (sevn CDP automator) with "
            f"action=social, site={site}, op={op}. "
            "Alternatively load playwright-browser / x-use / facebook-use / linkedin-use."
        ),
    }


async def execute_social_media_manager_task(
    task: str,
    *,
    content_root: Path,
    subagents_cfg: SubAgentsWorkspaceConfig | None = None,
) -> dict[str, Any]:
    """Run one ``social_media_manager`` job and return a result payload.

    Args:
        task (str): Spawn/skill task text.
        content_root (Path): Workspace content root.
        subagents_cfg (SubAgentsWorkspaceConfig | None): Optional preloaded config.

    Returns:
        dict[str, Any]: Result metadata (medium, op, data / plan / capabilities).

    Raises:
        TwexApiError: When specialist/API config is missing or TwexAPI fails.
        ValueError: When the task string is malformed.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(execute_social_media_manager_task)
        True
    """
    if subagents_cfg is None:
        cfg, _layout = load_workspace(start_dir=content_root)
        subagents_cfg = cfg.subagents
    specialist = require_social_media_manager(subagents_cfg)
    parsed = parse_social_media_task(task)
    skills = assigned_skills_for(specialist)
    tools = assigned_tools_for(specialist)

    if parsed.medium == "capabilities":
        settings, _cfg = load_twexapi_settings(content_root)
        return {
            "specialist": SOCIAL_MEDIA_MANAGER_SPECIALIST,
            "medium": "capabilities",
            "skills": skills,
            "tools": tools,
            "media": {
                "twexapi": {
                    "docs": settings.docs_url,
                    "base_url": settings.base_url,
                    "enabled": settings.enabled,
                    "ops": sorted(TWEXAPI_OPS),
                },
                "browser": {
                    "engine": "cdp",
                    "tool": "browser",
                    "skills": [
                        s
                        for s in (
                            "playwright-browser",
                            "browser-harness",
                            "x-use",
                            "facebook-use",
                            "linkedin-use",
                        )
                        if s in skills
                    ],
                },
            },
        }

    if parsed.medium == "browser":
        if "browser" not in tools:
            raise TwexApiError(
                "social_media_manager tools list does not include `browser` (CDP automator)"
            )
        return {
            "specialist": SOCIAL_MEDIA_MANAGER_SPECIALIST,
            **_browser_plan(parsed),
            "skills": skills,
            "tools": tools,
        }

    # medium == twexapi
    settings, _cfg = load_twexapi_settings(content_root)
    if not settings.enabled:
        raise TwexApiError("TwexAPI medium disabled (skills.social_media_manager.twexapi.enabled=false)")
    api_key = await resolve_twexapi_api_key(content_root=content_root, settings=settings)
    client = TwexApiClient(api_key, base_url=settings.base_url)
    op = parsed.op or "search"
    body = dict(parsed.body)
    params = dict(parsed.params)
    path_params = dict(parsed.path_params)
    if op == "search" and parsed.query and "searchTerms" not in body:
        body["searchTerms"] = [parsed.query]
    if op == "users" and parsed.query and "usernames" not in params:
        params["usernames"] = parsed.query
    if op == "replies_page" and "tweet_id" not in path_params:
        tweet_id = str(body.pop("tweet_id", "") or params.pop("tweet_id", "")).strip()
        if not tweet_id:
            raise TwexApiError("replies_page requires path_params.tweet_id")
        path_params["tweet_id"] = tweet_id
    data = await client.call_op(op, params=params or None, body=body or None, path_params=path_params or None)
    return {
        "specialist": SOCIAL_MEDIA_MANAGER_SPECIALIST,
        "medium": "twexapi",
        "op": op,
        "docs": settings.docs_url,
        "data": data,
        "skills": skills,
        "tools": tools,
    }


async def execute_social_media_manager_for_context(ctx: ToolContext, task: str) -> str:
    """Run a social-media specialist job from a spawn ``ToolContext``.

    Args:
        ctx (ToolContext): Spawn invocation context.
        task (str): Task string.

    Returns:
        str: JSON result payload.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(execute_social_media_manager_for_context)
        True
    """
    content_root = Path(ctx.workspace_path)
    subagents_cfg = None
    supervisor = ctx.subagent_supervisor
    if supervisor is not None:
        subagents_cfg = supervisor.config
    result = await execute_social_media_manager_task(
        task,
        content_root=content_root,
        subagents_cfg=subagents_cfg,
    )
    return json.dumps(result, separators=(",", ":"), default=str)
