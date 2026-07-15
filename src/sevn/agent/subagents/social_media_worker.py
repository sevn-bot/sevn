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
from sevn.integrations.twexapi.client import (
    TWEXAPI_ARRAY_BODY_OPS,
    TWEXAPI_OPS,
    TwexApiClient,
    TwexApiError,
)
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
_MAX_RESULT_JSON_CHARS = 48_000

# Declared toolkit for this specialist (surfaced via medium=capabilities).
# Parent/tier-B turns still load these via load_skill / browser when needed;
# the L2 worker itself executes TwexAPI and returns browser/CDP plans.
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

# Declared tools — includes sevn's native CDP ``browser`` automator.
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
    "SocialMediaManagerError",
    "SocialMediaTask",
    "assigned_skills_for",
    "assigned_tools_for",
    "execute_social_media_manager_for_context",
    "execute_social_media_manager_task",
    "parse_social_media_task",
    "require_social_media_manager",
]


class SocialMediaManagerError(RuntimeError):
    """Raised when the social_media_manager specialist is misconfigured."""


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
        SocialMediaManagerError: When the specialist is not configured.

    Examples:
        >>> require_social_media_manager(None)  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        SocialMediaManagerError
    """
    entry = resolve_specialist(cfg, SOCIAL_MEDIA_MANAGER_SPECIALIST)
    if entry is None:
        raise SocialMediaManagerError(SOCIAL_MEDIA_MANAGER_UNCONFIGURED)
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


def _capped_data(data: Any) -> Any:
    """Return ``data`` unchanged or a truncated stub when JSON is too large.

    Args:
        data (Any): TwexAPI response payload.

    Returns:
        Any: Original payload or a stub with ``truncated`` / ``preview``.

    Examples:
        >>> _capped_data({"ok": True})
        {'ok': True}
    """
    try:
        encoded = json.dumps(data, default=str)
    except (TypeError, ValueError):
        return {"truncated": True, "preview": str(data)[:_MAX_RESULT_JSON_CHARS]}
    if len(encoded) <= _MAX_RESULT_JSON_CHARS:
        return data
    return {
        "truncated": True,
        "original_chars": len(encoded),
        "max_chars": _MAX_RESULT_JSON_CHARS,
        "preview": encoded[:_MAX_RESULT_JSON_CHARS],
    }


def _normalize_twexapi_body(
    op: str,
    *,
    body: dict[str, Any],
    params: dict[str, Any],
    query: str | None,
) -> dict[str, Any] | list[Any] | None:
    """Build the JSON body for an allowlisted TwexAPI op.

    Args:
        op (str): Allowlisted op id.
        body (dict[str, Any]): Parsed object body from the task.
        params (dict[str, Any]): Query params (may hold username/id hints).
        query (str | None): Shorthand query string from the task.

    Returns:
        dict[str, Any] | list[Any] | None: Object or array body for the request.

    Examples:
        >>> _normalize_twexapi_body("users", body={}, params={}, query="elonmusk")
        ['elonmusk']
    """
    if op in TWEXAPI_ARRAY_BODY_OPS:
        if isinstance(body.get("items"), list):
            return [str(x) for x in body["items"]]
        for key in ("usernames", "user_ids", "tweet_ids", "ids"):
            raw = body.get(key, params.get(key))
            if isinstance(raw, list):
                return [str(x) for x in raw]
            if isinstance(raw, str) and raw.strip():
                return [part.strip() for part in raw.split(",") if part.strip()]
        if query:
            return [part.strip() for part in query.split(",") if part.strip()]
        return []
    out = dict(body)
    if op == "search" and query and "searchTerms" not in out:
        out["searchTerms"] = [query]
    return out or None


def _browser_plan(task: SocialMediaTask) -> dict[str, Any]:
    """Build a browser-medium plan that uses sevn's CDP ``browser`` tool.

    The L2 worker does not attach CDP itself (same boundary as other specialists
    that return structured results for the parent turn). The plan tells the
    caller to invoke the native ``browser`` tool with ``action=social``.

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
        SocialMediaManagerError: When the specialist is misconfigured.
        TwexApiError: When TwexAPI is disabled or the HTTP call fails.
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
            "note": (
                "skills/tools are the declared specialist toolkit (parent turns may "
                "load_skill / call browser). TwexAPI runs inside this L2 worker."
            ),
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
                    "mode": "plan",
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
            raise SocialMediaManagerError(
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
        raise SocialMediaManagerError(
            "TwexAPI medium disabled (skills.social_media_manager.twexapi.enabled=false)"
        )
    api_key = await resolve_twexapi_api_key(content_root=content_root, settings=settings)
    client = TwexApiClient(api_key, base_url=settings.base_url)
    op = parsed.op or "search"
    body = dict(parsed.body)
    params = dict(parsed.params)
    path_params = dict(parsed.path_params)
    if op == "replies_page" and "tweet_id" not in path_params:
        tweet_id = str(body.pop("tweet_id", "") or params.pop("tweet_id", "")).strip()
        if not tweet_id:
            raise TwexApiError("replies_page requires path_params.tweet_id")
        path_params["tweet_id"] = tweet_id
    if op == "timeline_page" and "screen_name" not in path_params:
        screen = str(
            body.pop("screen_name", "") or params.pop("screen_name", "") or (parsed.query or "")
        ).strip().lstrip("@")
        if not screen:
            raise TwexApiError("timeline_page requires path_params.screen_name")
        path_params["screen_name"] = screen
    if op == "trending_topics" and "country" not in path_params:
        country = str(
            body.pop("country", "") or params.pop("country", "") or (parsed.query or "worldwide")
        ).strip()
        path_params["country"] = country or "worldwide"
    request_body = _normalize_twexapi_body(
        op,
        body=body,
        params=params,
        query=parsed.query,
    )
    # Array-body ops do not use leftover query params for usernames/ids.
    if op in TWEXAPI_ARRAY_BODY_OPS:
        for key in ("usernames", "user_ids", "tweet_ids", "ids"):
            params.pop(key, None)
    data = await client.call_op(
        op,
        params=params or None,
        body=request_body,
        path_params=path_params or None,
    )
    return {
        "specialist": SOCIAL_MEDIA_MANAGER_SPECIALIST,
        "medium": "twexapi",
        "op": op,
        "docs": settings.docs_url,
        "data": _capped_data(data),
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
