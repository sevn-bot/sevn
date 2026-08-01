"""Draft-only Reddit post runtime helpers (#74, D11).

Module: sevn.integrations.reddit_karma.runtime
Depends: os, typing

Exports:
    reddit_post_modes — supported post modes (draft-only; no auto_post).
    require_reddit_post_confirm — CONFIRM_REQUIRED gate for writes.
    enforce_reddit_rate_limits — per-day caps and cooldown enforcement.
    strip_disallowed_links — remove URLs when links are not allowed.
    write_err — failure JSON envelope helper.
"""

from __future__ import annotations

import os
import re
from typing import Any

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_POST_MODES: frozenset[str] = frozenset({"draft_only"})


def reddit_post_modes() -> frozenset[str]:
    """Return supported Reddit post modes for this wave (D11 draft-only).

    Returns:
        frozenset[str]: Mode names; ``auto_post`` is intentionally absent.

    Examples:
        >>> modes = reddit_post_modes()
        >>> "auto_post" not in modes and "draft_only" in modes
        True
    """
    return _POST_MODES


def _confirm_posts_from_env() -> bool:
    """Return whether Reddit writes require ``--confirm`` from env.

    Returns:
        bool: ``True`` when confirmation is required (default).

    Examples:
        >>> _confirm_posts_from_env() in (True, False)
        True
    """
    raw = os.environ.get("SEVN_REDDIT_KARMA_CONFIRM_POSTS", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def write_err(
    *,
    code: str,
    message: str,
    detail: str | None = None,
    would_do: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a failure JSON envelope dict.

    Args:
        code (str): Stable error code.
        message (str): Operator-safe message.
        detail (str | None, optional): Optional detail string.
        would_do (dict[str, Any] | None, optional): Dry-run preview for writes.

    Returns:
        dict[str, Any]: ``{"ok": false, "error": {…}}``.

    Examples:
        >>> write_err(code="BAD_ARGS", message="missing body")["error"]["code"]
        'BAD_ARGS'
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    if would_do is not None:
        error["would_do"] = would_do
    return {"ok": False, "error": error}


def require_reddit_post_confirm(
    args: object,
    would_do: dict[str, Any],
    *,
    confirm_posts: bool | None = None,
) -> dict[str, Any] | None:
    """Return ``CONFIRM_REQUIRED`` when a Reddit write lacks ``--confirm`` (D11).

    ``ask_before_post`` is scaffolded off — confirmation is always required for
    live posts unless ``--dry-run`` is set on ``args``.

    Args:
        args (object): Parsed namespace with optional ``confirm`` / ``dry_run`` attrs.
        would_do (dict[str, Any]): Mutation preview for the operator.
        confirm_posts (bool | None, optional): Override env/config gate.

    Returns:
        dict[str, Any] | None: Error envelope when confirmation is required.

    Examples:
        >>> class _Args:
        ...     confirm = False
        ...     dry_run = False
        >>> preview = require_reddit_post_confirm(
        ...     _Args(), {"action": "post_comment", "subreddit": "test", "body": "hi"}
        ... )
        >>> preview is not None and preview["error"]["code"] == "CONFIRM_REQUIRED"
        True
    """
    if bool(getattr(args, "dry_run", False)):
        return None
    if confirm_posts is None:
        confirm_posts = _confirm_posts_from_env()
    if confirm_posts and not bool(getattr(args, "confirm", False)):
        return write_err(
            code="CONFIRM_REQUIRED",
            message="Reddit post requires operator approval; re-run with --confirm.",
            would_do=would_do,
        )
    return None


def enforce_reddit_rate_limits(
    *,
    posts_today: int,
    max_posts_per_day: int,
    cooldown_seconds: int,
    seconds_since_last_post: int,
) -> tuple[bool, str | None]:
    """Enforce per-day caps and cooldown windows (D11).

    Args:
        posts_today (int): Actions recorded for the current UTC day.
        max_posts_per_day (int): Configured daily cap (``0`` disables cap check).
        cooldown_seconds (int): Minimum spacing between actions.
        seconds_since_last_post (int): Elapsed seconds since the last action.

    Returns:
        tuple[bool, str | None]: ``(blocked, reason)``; ``reason`` is set when blocked.

    Examples:
        >>> enforce_reddit_rate_limits(
        ...     posts_today=5, max_posts_per_day=5, cooldown_seconds=0, seconds_since_last_post=999
        ... )[0]
        True
        >>> enforce_reddit_rate_limits(
        ...     posts_today=0, max_posts_per_day=10, cooldown_seconds=3600, seconds_since_last_post=30
        ... )[1]
        'cooldown active: wait 3570s before next Reddit action'
    """
    if max_posts_per_day > 0 and posts_today >= max_posts_per_day:
        return True, f"daily cap reached ({posts_today}/{max_posts_per_day})"
    if cooldown_seconds > 0 and seconds_since_last_post < cooldown_seconds:
        remaining = cooldown_seconds - seconds_since_last_post
        return True, f"cooldown active: wait {remaining}s before next Reddit action"
    return False, None


def strip_disallowed_links(body: str, *, allow_links: bool) -> str:
    """Remove URLs from draft/post bodies when links are disallowed (W33.8).

    Args:
        body (str): Comment body text.
        allow_links (bool): When ``True``, return ``body`` unchanged.

    Returns:
        str: Sanitized body.

    Examples:
        >>> strip_disallowed_links("see https://example.com", allow_links=False)
        'see [link removed]'
    """
    if allow_links:
        return body
    return _URL_RE.sub("[link removed]", body).strip()


__all__ = [
    "enforce_reddit_rate_limits",
    "reddit_post_modes",
    "require_reddit_post_confirm",
    "strip_disallowed_links",
    "write_err",
]
