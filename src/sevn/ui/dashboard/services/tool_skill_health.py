"""Tools & Skills health reader for Mission Control (`prd/07` §5.9).

Module: sevn.ui.dashboard.services.tool_skill_health
Depends: hashlib, json, sqlite3, sevn.config.defaults

Exports:
    ToolSkillHealthRow — one health table row dataclass.
    ToolSkillHealthService — chronic failure rows from ``sevn.db`` skills table.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from sevn.config.defaults import (
    DEFAULT_SKILL_FAILURE_REWRITE_THRESHOLD,
    DEFAULT_SKILL_FAILURE_WINDOW_DAYS,
)


@dataclass(frozen=True)
class ToolSkillHealthRow:
    """One health table row for dashboard or Telegram surfaces."""

    health_row_id: str
    layer: str
    name: str
    failure_count: int
    window_days: int
    last_failure_at: str | None
    last_failure_trace_id: str | None
    chronic: bool
    rewrite_candidate: bool


class ToolSkillHealthService:
    """Read denormalised skill failure rows; tools mirror deferred until DDL ships."""

    def __init__(
        self,
        *,
        workspace_id: str,
        window_days: int = DEFAULT_SKILL_FAILURE_WINDOW_DAYS,
        threshold: int = DEFAULT_SKILL_FAILURE_REWRITE_THRESHOLD,
    ) -> None:
        """Bind service to a workspace id used in ``skills`` SQLite rows.

        Args:
            workspace_id (str): Workspace key (typically ``workspace_root`` string).
            window_days (int, optional): Rolling window for display. Defaults to 14.
            threshold (int, optional): Chronic failure threshold. Defaults to 3.

        Examples:
            >>> svc = ToolSkillHealthService(workspace_id=".")
            >>> svc.workspace_id
            '.'
        """
        self.workspace_id = workspace_id
        self.window_days = window_days
        self.threshold = threshold

    @staticmethod
    def health_row_id(layer: str, name: str) -> str:
        """Stable opaque id for UI keys (`tool:<name>` / `skill:<name>`).

        Args:
            layer (str): ``tool`` or ``skill``.
            name (str): Tool or skill identifier.

        Returns:
            str: Hex digest prefix.

        Examples:
            >>> len(ToolSkillHealthService.health_row_id("skill", "demo"))
            16
        """
        raw = f"{layer}:{name}".encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def list_rows(
        self,
        conn: sqlite3.Connection,
        *,
        source: str = "dashboard",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return paginated health rows sorted by last failure descending.

        Args:
            conn (sqlite3.Connection): Open ``sevn.db`` connection.
            source (str, optional): Audit source label. Defaults to ``dashboard``.
            limit (int, optional): Max rows. Defaults to 200.

        Returns:
            list[dict[str, Any]]: Serialisable row dicts.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> rows = ToolSkillHealthService(workspace_id="w").list_rows(c)
            >>> rows == []
            True
            >>> c.close()
        """
        del source  # reserved for future lesson_decisions audit rows
        skill_rows = self._list_skill_rows(conn, limit=limit)
        rows = skill_rows
        rows.sort(
            key=lambda r: r.get("last_failure_at") or "",
            reverse=True,
        )
        return rows[:limit]

    def _list_skill_rows(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Load skill-layer rows from the ``skills`` health table.

        Args:
            conn (sqlite3.Connection): Open ``sevn.db`` connection.
            limit (int): Row cap.

        Returns:
            list[dict[str, Any]]: Skill health dicts.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> ToolSkillHealthService(workspace_id=".")._list_skill_rows(c, limit=10)
            []
            >>> c.close()
        """
        try:
            cur = conn.execute(
                """
                SELECT skill_name, failure_count, chronic_skill_failure,
                       failure_timestamps_json, updated_at_ns
                FROM skills
                WHERE workspace_id = ?
                ORDER BY updated_at_ns DESC
                LIMIT ?
                """,
                (self.workspace_id, limit),
            )
        except sqlite3.OperationalError:
            return []
        out: list[dict[str, Any]] = []
        for skill_name, failure_count, chronic_flag, ts_json, updated_ns in cur.fetchall():
            last_at, last_trace = _last_failure_from_timestamps(ts_json)
            if last_at is None and updated_ns:
                last_at = _ns_to_iso(int(updated_ns))
            chronic = bool(chronic_flag)
            rewrite = chronic or int(failure_count or 0) >= self.threshold
            if not rewrite and int(failure_count or 0) == 0:
                continue
            name = str(skill_name)
            out.append(
                {
                    "health_row_id": self.health_row_id("skill", name),
                    "layer": "skill",
                    "name": name,
                    "failure_count": int(failure_count or 0),
                    "window_days": self.window_days,
                    "last_failure_at": last_at,
                    "last_failure_trace_id": last_trace,
                    "chronic": chronic,
                    "rewrite_candidate": rewrite,
                },
            )
        return out


def _ns_to_iso(ns: int) -> str:
    """Convert epoch nanoseconds to ISO-8601 UTC string.

    Args:
        ns (int): Epoch nanoseconds.

    Returns:
        str: ISO timestamp or empty when invalid.

    Examples:
        >>> _ns_to_iso(1_700_000_000_000_000_000).startswith("2023")
        True
    """
    if ns <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ns / 1_000_000_000))
    except (OverflowError, OSError, ValueError):
        return ""


def _last_failure_from_timestamps(raw: object) -> tuple[str | None, str | None]:
    """Parse ``failure_timestamps_json`` for last failure time and trace id.

    Args:
        raw (object): SQLite column value.

    Returns:
        tuple[str | None, str | None]: ``(last_failure_at, last_failure_trace_id)``.

    Examples:
        >>> _last_failure_from_timestamps("[]")
        (None, None)
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(parsed, list) or not parsed:
        return None, None
    last = parsed[-1]
    trace_id: str | None = None
    ts_ns: int | None = None
    if isinstance(last, dict):
        raw_ts = last.get("ts_ns") or last.get("at_ns")
        if isinstance(raw_ts, (int, float)):
            ts_ns = int(raw_ts)
        raw_trace = last.get("trace_id")
        if isinstance(raw_trace, str) and raw_trace.strip():
            trace_id = raw_trace.strip()
    elif isinstance(last, (int, float)):
        ts_ns = int(last)
    last_at = _ns_to_iso(ts_ns) if ts_ns is not None else None
    return last_at, trace_id


__all__ = ["ToolSkillHealthRow", "ToolSkillHealthService"]
