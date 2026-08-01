"""Reddit karma loop orchestration (#74, W33).

Module: sevn.integrations.reddit_karma.loop
Depends: pathlib, typing, sevn.integrations.reddit_karma.config, log, quality_gate, runtime

Exports:
    build_discovery_browser_plan — browser ``site=reddit`` discovery task (D10).
    render_comment_draft — template render with optional link stripping.
    run_draft_loop — discover → gate → draft with structured logging.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — runtime workspace root in loop orchestration
from typing import Any

from sevn.integrations.reddit_karma.config import RedditKarmaConfig, resolve_reddit_karma_config
from sevn.integrations.reddit_karma.log import RedditDecisionLog
from sevn.integrations.reddit_karma.quality_gate import candidate_from_dict, evaluate_candidate
from sevn.integrations.reddit_karma.runtime import (
    enforce_reddit_rate_limits,
    strip_disallowed_links,
)


def build_discovery_browser_plan(
    cfg: RedditKarmaConfig,
    *,
    subreddit: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Return a browser-tool plan for Reddit discovery (D10 — no new API).

    Uses the same ``browser`` ``action=social`` ``site=reddit`` path as
    ``social_media_manager`` (``SKILL.md`` platform matrix).

    Args:
        cfg (RedditKarmaConfig): Effective loop config.
        subreddit (str | None, optional): Target subreddit override.
        query (str | None, optional): Search query override.

    Returns:
        dict[str, Any]: Browser task envelope for the parent turn to execute.

    Examples:
        >>> plan = build_discovery_browser_plan(RedditKarmaConfig(subreddits=("python",)))
        >>> plan["site"]
        'reddit'
    """
    target_sub = (subreddit or (cfg.subreddits[0] if cfg.subreddits else "")).removeprefix("r/")
    search_query = query or (cfg.topics[0] if cfg.topics else "help")
    return {
        "tool": "browser",
        "action": "social",
        "site": "reddit",
        "op": "search",
        "query": search_query,
        "url": f"https://www.reddit.com/r/{target_sub}/"
        if target_sub
        else "https://www.reddit.com/",
        "medium": "browser",
        "note": "Discovery only — loop drafts comments; D11 draft-only (no auto_post).",
    }


def render_comment_draft(
    *,
    candidate_title: str,
    subreddit: str,
    grounding_snippet: str,
    template: str,
    allow_links: bool,
) -> str:
    """Render a comment draft from the bundled template.

    Args:
        candidate_title (str): Thread title placeholder.
        subreddit (str): Target subreddit name.
        grounding_snippet (str): Wiki/second-brain excerpt.
        template (str): Markdown template with ``{{placeholders}}``.
        allow_links (bool): When false, strip URLs from the rendered body.

    Returns:
        str: Rendered comment body.

    Examples:
        >>> render_comment_draft(
        ...     candidate_title="Q", subreddit="python", grounding_snippet="note",
        ...     template="Re {{title}}", allow_links=True,
        ... )
        'Re Q'
    """
    body = (
        template.replace("{{title}}", candidate_title)
        .replace("{{subreddit}}", subreddit)
        .replace("{{grounding}}", grounding_snippet.strip())
    )
    return strip_disallowed_links(body, allow_links=allow_links)


def run_draft_loop(
    workspace: Path,
    workspace_cfg: object,
    *,
    candidates: list[dict[str, Any]] | None = None,
    template: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run discover → gate → draft for supplied or planned candidates.

    When ``candidates`` is omitted, returns the browser discovery plan only.
    Every candidate, skip, and draft is appended to the decision log (W33.7).

    Args:
        workspace (Path): Workspace content root.
        workspace_cfg (object): Parsed :class:`~sevn.config.workspace_config.WorkspaceConfig`.
        candidates (list[dict[str, Any]] | None, optional): Pre-fetched discovery rows.
        template (str): Comment draft markdown template text.
        dry_run (bool): When ``True``, never record post actions.

    Returns:
        dict[str, Any]: Summary envelope with plans, drafts, and skip reasons.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     out = run_draft_loop(Path(tmp), WorkspaceConfig.minimal(), template="x")
        ...     out["ok"]
        True
    """
    cfg = resolve_reddit_karma_config(workspace_cfg)  # type: ignore[arg-type]
    log = RedditDecisionLog(workspace)
    allowed = frozenset(s.lower() for s in cfg.subreddits)

    blocked, block_reason = enforce_reddit_rate_limits(
        posts_today=log.posts_today_count(),
        max_posts_per_day=cfg.max_comments_per_day,
        cooldown_seconds=cfg.cooldown_seconds,
        seconds_since_last_post=log.seconds_since_last_post(),
    )
    if blocked:
        log.append(event="skip", skip_reason=block_reason, action="rate_limit")
        return {
            "ok": True,
            "dry_run": dry_run,
            "blocked": True,
            "reason": block_reason,
            "discovery_plan": build_discovery_browser_plan(cfg),
        }

    if candidates is None:
        plan = build_discovery_browser_plan(cfg)
        log.append(event="candidate", action="discovery_plan", extra={"plan": plan})
        return {"ok": True, "dry_run": dry_run, "discovery_plan": plan, "drafts": []}

    drafts: list[dict[str, Any]] = []
    for raw in candidates:
        log.append(event="candidate", candidate=raw)
        normalized = candidate_from_dict(raw, allowed_subreddits=allowed)
        accepted, skip_reason = evaluate_candidate(normalized)
        if not accepted:
            log.append(event="skip", candidate=raw, skip_reason=skip_reason, url=normalized.url)
            continue
        grounding = str(raw.get("grounding_snippet") or "See operator wiki / second-brain sources.")
        body = render_comment_draft(
            candidate_title=normalized.title,
            subreddit=normalized.subreddit,
            grounding_snippet=grounding,
            template=template,
            allow_links=cfg.allow_links,
        )
        draft = {
            "subreddit": normalized.subreddit,
            "url": normalized.url,
            "body": body,
            "mode": "draft_only",
            "source_paths": list(cfg.source_paths),
            "tools_for_grounding": ["wiki_search", "wiki_read", "second_brain_query"],
        }
        log.append(
            event="draft", candidate=raw, draft=draft, url=normalized.url, action="draft_only"
        )
        drafts.append(draft)

    return {
        "ok": True,
        "dry_run": dry_run,
        "blocked": False,
        "drafts": drafts,
        "modes": sorted({"draft_only"}),
    }


__all__ = [
    "build_discovery_browser_plan",
    "render_comment_draft",
    "run_draft_loop",
]
