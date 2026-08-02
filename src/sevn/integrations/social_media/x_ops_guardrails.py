"""Dry-run, rate-limit, and reply-filter guardrails for X ops dispatch.

Module: sevn.integrations.social_media.x_ops_guardrails
Depends: sevn.integrations.social_media.x_ops_dispatch.envelope

Exports:
    apply_pre_dispatch_guards — unified dry-run / rate-limit gate.
    filter_new_comments — since_id reply filter for TwexAPI payloads.
    task_dry_run — parse dry_run flag from task payload.
    task_force_rate_limit — parse force_rate_limit test hook from task payload.
    dry_run_envelope — build DRY_RUN success envelope.
    rate_limit_envelope — build RATE_LIMITED failure envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sevn.integrations.social_media.x_ops_dispatch import _OpSpec

ENGAGEMENT_OPS: frozenset[str] = frozenset({"comment_on_tweet", "react_tweet"})
TIMELINE_READ_OPS: frozenset[str] = frozenset(
    {"get_new_comments_on_tweet", "get_tweet_stats", "collect_tweet_replies"}
)
DISCOVERY_OPS: frozenset[str] = frozenset(
    {"discover_followers", "discover_topic_accounts", "discover_mutual_graph"}
)

# Backward-compatible wave-plan aliases (tests use local tuples; avoid new imports).
W12_ENGAGEMENT_OPS = ENGAGEMENT_OPS
W13_TIMELINE_OPS = TIMELINE_READ_OPS
W14_DISCOVERY_OPS = DISCOVERY_OPS

EXPANSION_OPS: frozenset[str] = ENGAGEMENT_OPS | TIMELINE_READ_OPS | DISCOVERY_OPS

__all__ = [
    "DISCOVERY_OPS",
    "ENGAGEMENT_OPS",
    "EXPANSION_OPS",
    "TIMELINE_READ_OPS",
    "W12_ENGAGEMENT_OPS",
    "W13_TIMELINE_OPS",
    "W14_DISCOVERY_OPS",
    "apply_pre_dispatch_guards",
    "filter_new_comments",
    "task_dry_run",
    "task_force_rate_limit",
]


def _truthy_task_flag(task: dict[str, Any], key: str) -> bool:
    """Return whether a task field is truthy (bool or common string forms).

    Args:
        task (dict[str, Any]): Task payload.
        key (str): Field name.

    Returns:
        bool: Parsed truthiness.

    Examples:
        >>> _truthy_task_flag({"dry_run": "yes"}, "dry_run")
        True
    """
    raw = task.get(key)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def task_force_rate_limit(task: dict[str, Any]) -> bool:
    """Return whether the task simulates a rate-limit response (tests / guardrails).

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        bool: True when ``force_rate_limit`` is truthy.

    Examples:
        >>> task_force_rate_limit({"force_rate_limit": True})
        True
    """
    return _truthy_task_flag(task, "force_rate_limit")


def task_dry_run(task: dict[str, Any]) -> bool:
    """Return whether the task requests a dry-run (no live writes).

    Args:
        task (dict[str, Any]): Task payload.

    Returns:
        bool: True when ``dry_run`` is truthy.

    Examples:
        >>> task_dry_run({"dry_run": True})
        True
    """
    return _truthy_task_flag(task, "dry_run")


def dry_run_envelope(op: str, medium: str, task: dict[str, Any]) -> dict[str, Any]:
    """Build a planned-action envelope for write/read ops under dry-run (D11).

    Args:
        op (str): Facade op name.
        medium (str): Resolved medium.
        task (dict[str, Any]): Task payload (secrets omitted from ``data.task``).

    Returns:
        dict[str, Any]: Success envelope with ``code=DRY_RUN``.

    Examples:
        >>> dry_run_envelope("react_tweet", "browser", {"dry_run": True})["code"]
        'DRY_RUN'
    """
    from sevn.integrations.social_media.x_ops_dispatch import envelope

    safe_task = {k: v for k, v in task.items() if k not in ("cookie", "export_cookies", "cookies")}
    planned: dict[str, Any] = {"dry_run": True, "planned": True, "task": safe_task}
    if op in TIMELINE_READ_OPS:
        planned["read"] = True
    if op in DISCOVERY_OPS:
        planned["read"] = True
        planned["discovery"] = True
    return envelope(
        ok=True,
        medium=medium,
        op=op,
        data=planned,
        code="DRY_RUN",
    )


def rate_limit_envelope(op: str, medium: str, *, retry_after_s: int = 30) -> dict[str, Any]:
    """Build a machine-readable rate-limit envelope for discovery ops (D11).

    Args:
        op (str): Facade op name.
        medium (str): Resolved medium.
        retry_after_s (int): Suggested backoff seconds.

    Returns:
        dict[str, Any]: Failure envelope with ``code=RATE_LIMITED``.

    Examples:
        >>> rate_limit_envelope("discover_followers", "twexapi")["code"]
        'RATE_LIMITED'
    """
    from sevn.integrations.social_media.x_ops_dispatch import envelope

    return envelope(
        ok=False,
        medium=medium,
        op=op,
        data={"retry_after_s": retry_after_s},
        error="rate limited — retry after backoff",
        code="RATE_LIMITED",
    )


def apply_pre_dispatch_guards(
    op: str,
    spec: _OpSpec,
    task: dict[str, Any],
    medium: str,
) -> dict[str, Any] | None:
    """Apply dry-run and discovery rate-limit gates before medium dispatch.

    Args:
        op (str): Facade op name.
        spec (_OpSpec): OpSpec row for ``op``.
        task (dict[str, Any]): Task payload.
        medium (str): Resolved medium.

    Returns:
        dict[str, Any] | None: Early envelope when a guard fires; else ``None``.

    Examples:
        >>> from sevn.integrations.social_media.x_ops_dispatch import _OpSpec
        >>> spec = _OpSpec("discover_followers")
        >>> out = apply_pre_dispatch_guards(
        ...     "discover_followers", spec, {"dry_run": True}, "twexapi"
        ... )
        >>> out is not None and out["code"] == "DRY_RUN"
        True
    """
    if op in DISCOVERY_OPS and task_force_rate_limit(task):
        retry_raw = task.get("retry_after_s")
        retry_after_s = int(retry_raw) if retry_raw is not None else 30
        return rate_limit_envelope(op, medium, retry_after_s=retry_after_s)
    if task_dry_run(task) and spec.dry_run_eligible:
        return dry_run_envelope(op, medium, task)
    return None


def _reply_item_id(item: Any) -> str | None:
    """Extract a reply tweet id from a TwexAPI/browser reply item.

    Args:
        item (Any): Reply record.

    Returns:
        str | None: Tweet id when present.

    Examples:
        >>> _reply_item_id({"id": "9"})
        '9'
    """
    if not isinstance(item, dict):
        return None
    for key in ("id", "tweet_id", "rest_id", "id_str"):
        raw = item.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _extract_reply_items(data: Any) -> list[Any]:
    """Return a reply list from common TwexAPI/browser payload shapes.

    Args:
        data (Any): API or parsed browser payload.

    Returns:
        list[Any]: Reply items (may be empty).

    Examples:
        >>> _extract_reply_items({"replies": [{"id": "1"}]})[0]["id"]
        '1'
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("replies", "comments", "items", "tweets", "data"):
            raw = data.get(key)
            if isinstance(raw, list):
                return raw
    return []


def filter_new_comments(data: Any, task: dict[str, Any]) -> Any:
    """Keep only replies newer than ``since_id`` / ``last_seen_id`` when set.

    Args:
        data (Any): Raw replies payload.
        task (dict[str, Any]): Task with optional ``since_id`` / ``last_seen_id``.

    Returns:
        Any: Filtered payload (same top-level shape when possible).

    Examples:
        >>> out = filter_new_comments(
        ...     {"replies": [{"id": "2"}, {"id": "1"}]},
        ...     {"since_id": "1"},
        ... )
        >>> out["replies"][0]["id"]
        '2'
    """
    since_raw = (
        task.get("since_id") if task.get("since_id") is not None else task.get("last_seen_id")
    )
    if since_raw is None or not str(since_raw).strip():
        return data
    since_s = str(since_raw).strip()
    items = _extract_reply_items(data)
    if not items:
        return data
    filtered: list[Any] = []
    for item in items:
        reply_id = _reply_item_id(item)
        if reply_id is None:
            filtered.append(item)
            continue
        try:
            if int(reply_id) > int(since_s):
                filtered.append(item)
        except ValueError:
            if reply_id != since_s:
                filtered.append(item)
    if isinstance(data, list):
        return filtered
    if isinstance(data, dict):
        out = dict(data)
        for key in ("replies", "comments", "items", "tweets", "data"):
            if key in out and isinstance(out[key], list):
                out[key] = filtered
                break
        else:
            out["items"] = filtered
        out["filtered_since_id"] = since_s
        out["new_count"] = len(filtered)
        return out
    return data
