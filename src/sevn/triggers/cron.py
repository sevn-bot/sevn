"""SQLite-backed cron job store (`specs/30-non-interactive-triggers.md` §2.4, §3.2).
Module: sevn.triggers.cron
Depends: croniter, sqlite3, time, zoneinfo
Exports:
    CronJobRow — ORM-shaped row for due jobs.
    CronJobDetail — full ``trigger_cron_jobs`` row for agent CRUD.
    SqliteCronStore — persistence helper.
    compute_next_fire_ns — bump ``next_fire_at_ns`` using croniter.
    cron_job_to_dict — JSON-serialisable projection of :class:`CronJobDetail`.
    cron_job_to_list_dict — list-envelope projection with ISO ``next_fire_at``.
    format_next_fire_at_iso — epoch-ns to ISO-8601 UTC for skill envelopes.
    list_cron_jobs — list all persisted cron rows.
    add_cron_job — insert a cron job row.
    edit_cron_job — patch an existing cron job row.
    delete_cron_job — remove a cron job row.
    add_reminder — one-shot reminder row (cron at absolute datetime).
    register_cron_job_handler — bind a job_id to a sync handler (no magic forks).
    cron_tick — gateway lifespan hook (loads due jobs; dispatch is injected).

Issue-watch cron lives in :mod:`sevn.triggers.issue_watch_cron` (imported at boot).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.triggers.request import DeliveryMode, DispatchRequest, ResultChannel, RoutingMode

# job_id → sync handler ``(*, workspace: Path) -> None`` (avoids magic forks in cron_tick).
_CRON_JOB_HANDLERS: dict[str, Callable[..., Any]] = {}


def register_cron_job_handler(job_id: str, handler: Callable[..., Any]) -> None:
    """Bind ``job_id`` to a sync cron handler (called from :func:`cron_tick`).

    Args:
        job_id (str): Persisted ``trigger_cron_jobs.job_id``.
        handler (Callable[..., Any]): Sync callable; receives ``workspace=``.

    Returns:
        None

    Examples:
        >>> register_cron_job_handler("demo", lambda **_k: None)
        >>> "demo" in _CRON_JOB_HANDLERS
        True
        >>> _ = _CRON_JOB_HANDLERS.pop("demo", None)
    """
    _CRON_JOB_HANDLERS[job_id.strip()] = handler


@dataclass(frozen=True)
class CronJobRow:
    """Subset of ``trigger_cron_jobs`` columns used by ``cron_tick``."""

    job_id: str
    cron_expr: str
    timezone: str
    next_fire_at_ns: int
    routing_mode: RoutingMode
    delivery_mode: DeliveryMode
    permission_template_ref: str
    allow_tier_cd: bool
    overlap_policy: str
    result_channel_json: str
    payload_template: str


@dataclass(frozen=True)
class CronJobDetail:
    """Full ``trigger_cron_jobs`` row for bundled scheduling skill CRUD."""

    job_id: str
    enabled: bool
    cron_expr: str
    timezone: str
    next_fire_at_ns: int
    jitter_s: int
    routing_mode: RoutingMode
    delivery_mode: DeliveryMode
    permission_template_ref: str
    allow_tier_cd: bool
    overlap_policy: str
    result_channel_json: str
    payload_template: str | None
    last_correlation_id: str | None
    last_status: str | None


def _normalize_routing_mode(value: str | None) -> RoutingMode:
    """Return a valid routing mode literal.

    Args:
        value (str | None): Raw persisted or CLI value.

    Returns:
        RoutingMode: ``fixed`` or ``auto_route``.

    Examples:
        >>> _normalize_routing_mode("auto_route")
        'auto_route'
        >>> _normalize_routing_mode("bogus")
        'fixed'
    """
    if value in ("fixed", "auto_route"):
        return value  # type: ignore[return-value]
    return "fixed"


def _normalize_delivery_mode(value: str | None) -> DeliveryMode:
    """Return a valid delivery mode literal.

    Args:
        value (str | None): Raw persisted or CLI value.

    Returns:
        DeliveryMode: ``agent_pass`` or ``notify_only``.

    Examples:
        >>> _normalize_delivery_mode("notify_only")
        'notify_only'
        >>> _normalize_delivery_mode(None)
        'agent_pass'
    """
    if value in ("agent_pass", "notify_only"):
        return value  # type: ignore[return-value]
    return "agent_pass"


def _normalize_overlap_policy(value: str | None) -> str:
    """Return a valid overlap policy label.

    Args:
        value (str | None): Raw persisted or CLI value.

    Returns:
        str: ``skip``, ``queue``, or ``allow``.

    Examples:
        >>> _normalize_overlap_policy("queue")
        'queue'
        >>> _normalize_overlap_policy("x")
        'skip'
    """
    if value in ("skip", "queue", "allow"):
        return value
    return "skip"


def _validate_cron_expr(cron_expr: str) -> str:
    """Validate a five-field cron expression via ``croniter``.

    Args:
        cron_expr (str): Cron schedule string.

    Returns:
        str: Stripped expression.

    Raises:
        ValueError: When ``croniter`` rejects the expression.

    Examples:
        >>> _validate_cron_expr("0 * * * *")
        '0 * * * *'
    """
    expr = cron_expr.strip()
    if not expr:
        msg = "cron_expr must be non-empty"
        raise ValueError(msg)
    try:
        croniter(expr)
    except (KeyError, ValueError) as exc:
        msg = f"invalid cron expression: {expr}"
        raise ValueError(msg) from exc
    return expr


def _sqlite_int(value: object, *, default: int = 0) -> int:
    """Coerce a SQLite column value to ``int``.

    Args:
        value (object): Cell from ``sqlite3`` row tuple.
        default (int, optional): Value when ``value`` is ``None``. Defaults to ``0``.

    Returns:
        int: Coerced integer.

    Examples:
        >>> _sqlite_int(3)
        3
        >>> _sqlite_int(None, default=0)
        0
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return int(str(value))


def _detail_from_row(row: tuple[object, ...]) -> CronJobDetail:
    """Map a ``trigger_cron_jobs`` SELECT row to :class:`CronJobDetail`.

    Args:
        row (tuple[object, ...]): Fifteen-column query result.

    Returns:
        CronJobDetail: Parsed job record.

    Examples:
        >>> d = _detail_from_row(
        ...     ("j", 1, "0 * * * *", "UTC", 1, 0, "fixed", "agent_pass", "default", 0,
        ...      "skip", "{}", "hi", None, None),
        ... )
        >>> d.job_id
        'j'
    """
    return CronJobDetail(
        job_id=str(row[0]),
        enabled=bool(row[1]),
        cron_expr=str(row[2]),
        timezone=str(row[3] or "UTC"),
        next_fire_at_ns=_sqlite_int(row[4]),
        jitter_s=_sqlite_int(row[5]),
        routing_mode=_normalize_routing_mode(str(row[6]) if row[6] is not None else None),
        delivery_mode=_normalize_delivery_mode(str(row[7]) if row[7] is not None else None),
        permission_template_ref=str(row[8] or "default"),
        allow_tier_cd=bool(row[9]),
        overlap_policy=_normalize_overlap_policy(str(row[10]) if row[10] is not None else None),
        result_channel_json=str(row[11] or "{}"),
        payload_template=str(row[12]) if row[12] is not None else None,
        last_correlation_id=str(row[13]) if row[13] is not None else None,
        last_status=str(row[14]) if row[14] is not None else None,
    )


def format_next_fire_at_iso(ns: int) -> str:
    """Convert epoch nanoseconds to ISO-8601 UTC for skill list envelopes.

    Args:
        ns (int): ``next_fire_at_ns`` from ``trigger_cron_jobs``.

    Returns:
        str: ISO timestamp, or empty when ``ns`` is not positive.

    Examples:
        >>> format_next_fire_at_iso(1780455600000000000).startswith("2026-06-03")
        True
    """
    if ns <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ns / 1e9, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return ""


def cron_job_to_dict(job: CronJobDetail) -> dict[str, object]:
    """Project :class:`CronJobDetail` for JSON tool envelopes.

    Args:
        job (CronJobDetail): Persisted cron row.

    Returns:
        dict[str, object]: Plain dict suitable for ``write_ok``.

    Examples:
        >>> from sevn.triggers.cron import CronJobDetail, cron_job_to_dict
        >>> cron_job_to_dict(
        ...     CronJobDetail(
        ...         job_id="j", enabled=True, cron_expr="0 * * * *", timezone="UTC",
        ...         next_fire_at_ns=1, jitter_s=0, routing_mode="fixed",
        ...         delivery_mode="agent_pass", permission_template_ref="default",
        ...         allow_tier_cd=False, overlap_policy="skip", result_channel_json="{}",
        ...         payload_template=None, last_correlation_id=None, last_status=None,
        ...     ),
        ... )["job_id"]
        'j'
    """
    return {
        "job_id": job.job_id,
        "enabled": job.enabled,
        "cron_expr": job.cron_expr,
        "timezone": job.timezone,
        "next_fire_at_ns": job.next_fire_at_ns,
        "jitter_s": job.jitter_s,
        "routing_mode": job.routing_mode,
        "delivery_mode": job.delivery_mode,
        "permission_template_ref": job.permission_template_ref,
        "allow_tier_cd": job.allow_tier_cd,
        "overlap_policy": job.overlap_policy,
        "result_channel_json": job.result_channel_json,
        "payload_template": job.payload_template,
        "last_correlation_id": job.last_correlation_id,
        "last_status": job.last_status,
    }


def cron_job_to_list_dict(job: CronJobDetail) -> dict[str, object]:
    """Project a cron row for ``cron_list`` / ``cron_status`` skill envelopes.

    Adds human-readable ``next_fire_at`` (ISO UTC) alongside ``next_fire_at_ns`` so
    executors never convert nanoseconds client-side.

    Args:
        job (CronJobDetail): Persisted cron row.

    Returns:
        dict[str, object]: :func:`cron_job_to_dict` plus ``next_fire_at``.

    Examples:
        >>> from sevn.triggers.cron import CronJobDetail, cron_job_to_list_dict
        >>> row = cron_job_to_list_dict(
        ...     CronJobDetail(
        ...         job_id="j", enabled=True, cron_expr="0 * * * *", timezone="UTC",
        ...         next_fire_at_ns=1780455600000000000, jitter_s=0, routing_mode="fixed",
        ...         delivery_mode="agent_pass", permission_template_ref="default",
        ...         allow_tier_cd=False, overlap_policy="skip", result_channel_json="{}",
        ...         payload_template=None, last_correlation_id=None, last_status=None,
        ...     ),
        ... )
        >>> row["next_fire_at"].startswith("2026-06-03")
        True
    """
    data = cron_job_to_dict(job)
    data["next_fire_at"] = format_next_fire_at_iso(job.next_fire_at_ns)
    return data


class SqliteCronStore:
    """Read/write helper for ``trigger_cron_jobs``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Attach a SQLite connection used for cron row IO.
        Args:
            conn (sqlite3.Connection): Shared ``sevn.db`` handle (caller manages WAL).
        Examples:
            >>> import sqlite3
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> SqliteCronStore(sqlite3.connect(":memory:"))  # doctest: +ELLIPSIS
            <sevn.triggers.cron.SqliteCronStore object at ...>
        """
        self._conn = conn

    def list_due(self, now_ns: int) -> list[CronJobRow]:
        """Return enabled jobs due at or before ``now_ns``.
        Args:
            now_ns (int): Current time in nanoseconds (``time.time_ns()``).
        Returns:
            list[CronJobRow]: Rows ordered by ``next_fire_at_ns`` ascending.
        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> SqliteCronStore(c).list_due(10**18)
            []
        """
        cur = self._conn.execute(
            """
            SELECT job_id, cron_expr, timezone, next_fire_at_ns, routing_mode, delivery_mode,
                   permission_template_ref, allow_tier_cd, overlap_policy, result_channel_json,
                   COALESCE(payload_template, '')
            FROM trigger_cron_jobs
            WHERE enabled = 1 AND next_fire_at_ns <= ?
            ORDER BY next_fire_at_ns ASC
            """,
            (int(now_ns),),
        )
        rows: list[CronJobRow] = []
        for r in cur.fetchall():
            rm = str(r[4]) if r[4] in ("fixed", "auto_route") else "fixed"
            dm = str(r[5]) if r[5] in ("agent_pass", "notify_only") else "agent_pass"
            rows.append(
                CronJobRow(
                    job_id=str(r[0]),
                    cron_expr=str(r[1]),
                    timezone=str(r[2]) if r[2] else "UTC",
                    next_fire_at_ns=int(r[3]),
                    routing_mode=rm,  # type: ignore[arg-type]
                    delivery_mode=dm,  # type: ignore[arg-type]
                    permission_template_ref=str(r[6] or "default"),
                    allow_tier_cd=bool(r[7]),
                    overlap_policy=str(r[8] or "skip"),
                    result_channel_json=str(r[9] or "{}"),
                    payload_template=str(r[10] or ""),
                ),
            )
        return rows

    def update_schedule(
        self,
        *,
        job_id: str,
        next_fire_at_ns: int,
        last_correlation_id: str | None,
        last_status: str | None,
    ) -> None:
        """Persist next fire time and last run metadata after a dispatch attempt.
        Args:
            job_id (str): Primary key in ``trigger_cron_jobs``.
            next_fire_at_ns (int): Next scheduled fire (nanoseconds).
            last_correlation_id (str | None): Correlation id from last attempt.
            last_status (str | None): Short status label (``ok``, ``error``, …).
        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> store = SqliteCronStore(c)
            >>> store.update_schedule(
            ...     job_id="j", next_fire_at_ns=1, last_correlation_id=None, last_status=None,
            ... )
        """
        self._conn.execute(
            """
            UPDATE trigger_cron_jobs
            SET next_fire_at_ns = ?, last_correlation_id = ?, last_status = ?
            WHERE job_id = ?
            """,
            (int(next_fire_at_ns), last_correlation_id, last_status, job_id),
        )
        self._conn.commit()

    def _select_columns(self) -> str:
        """Return the shared SELECT column list for full cron rows.

        Returns:
            str: SQL fragment listing ``trigger_cron_jobs`` columns.

        Examples:
            >>> SqliteCronStore.__name__
            'SqliteCronStore'
        """
        return """
            job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
            routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
            overlap_policy, result_channel_json, payload_template,
            last_correlation_id, last_status
        """

    def list_jobs(self) -> list[CronJobDetail]:
        """Return all cron rows ordered by ``job_id``.

        Returns:
            list[CronJobDetail]: Every persisted job.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> SqliteCronStore(c).list_jobs()
            []
        """
        cur = self._conn.execute(
            f"SELECT {self._select_columns()} FROM trigger_cron_jobs ORDER BY job_id",  # nosec B608 — column list is fixed
        )
        return [_detail_from_row(tuple(r)) for r in cur.fetchall()]

    def get_job(self, job_id: str) -> CronJobDetail | None:
        """Fetch one cron row by primary key.

        Args:
            job_id (str): ``trigger_cron_jobs.job_id``.

        Returns:
            CronJobDetail | None: Row when present.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> SqliteCronStore(c).get_job("missing") is None
            True
        """
        cur = self._conn.execute(
            f"SELECT {self._select_columns()} FROM trigger_cron_jobs WHERE job_id = ?",  # nosec B608 — column list is fixed
            (job_id.strip(),),
        )
        row = cur.fetchone()
        return _detail_from_row(tuple(row)) if row is not None else None

    def insert_job(
        self,
        *,
        job_id: str,
        cron_expr: str,
        timezone: str = "UTC",
        enabled: bool = True,
        jitter_s: int = 0,
        routing_mode: RoutingMode = "fixed",
        delivery_mode: DeliveryMode = "agent_pass",
        permission_template_ref: str = "default",
        allow_tier_cd: bool = False,
        overlap_policy: str = "skip",
        result_channel_json: str = "{}",
        payload_template: str | None = None,
        next_fire_at_ns: int | None = None,
    ) -> CronJobDetail:
        """Insert a cron job and return the persisted row.

        Args:
            job_id (str): Primary key (must be unique).
            cron_expr (str): Five-field cron schedule.
            timezone (str, optional): IANA zone. Defaults to ``UTC``.
            enabled (bool, optional): Whether the job is active. Defaults to ``True``.
            jitter_s (int, optional): Jitter seconds. Defaults to ``0``.
            routing_mode (RoutingMode, optional): Routing mode. Defaults to ``fixed``.
            delivery_mode (DeliveryMode, optional): Delivery mode. Defaults to ``agent_pass``.
            permission_template_ref (str, optional): Template ref. Defaults to ``default``.
            allow_tier_cd (bool, optional): Tier C/D allowance. Defaults to ``False``.
            overlap_policy (str, optional): Overlap policy. Defaults to ``skip``.
            result_channel_json (str, optional): Serialised :class:`~sevn.triggers.request.ResultChannel`.
            payload_template (str | None, optional): Prompt or notify template body.
            next_fire_at_ns (int | None, optional): Override first fire instant.

        Returns:
            CronJobDetail: Inserted row.

        Raises:
            ValueError: Duplicate ``job_id`` or invalid cron expression.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> job = SqliteCronStore(c).insert_job(
            ...     job_id="demo", cron_expr="0 12 * * *", payload_template="noon check",
            ... )
            >>> job.job_id
            'demo'
        """
        jid = job_id.strip()
        if not jid:
            msg = "job_id must be non-empty"
            raise ValueError(msg)
        expr = _validate_cron_expr(cron_expr)
        tz = (timezone or "UTC").strip() or "UTC"
        now_ns = time.time_ns()
        nxt = (
            int(next_fire_at_ns)
            if next_fire_at_ns is not None
            else compute_next_fire_ns(cron_expr=expr, tz_name=tz, from_ns=now_ns)
        )
        overlap = _normalize_overlap_policy(overlap_policy)
        if self.get_job(jid) is not None:
            msg = f"job_id already exists: {jid}"
            raise ValueError(msg)
        self._conn.execute(
            """
            INSERT INTO trigger_cron_jobs (
                job_id, enabled, cron_expr, timezone, next_fire_at_ns, jitter_s,
                routing_mode, delivery_mode, permission_template_ref, allow_tier_cd,
                overlap_policy, result_channel_json, payload_template
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                jid,
                1 if enabled else 0,
                expr,
                tz,
                nxt,
                int(jitter_s),
                routing_mode,
                delivery_mode,
                permission_template_ref.strip() or "default",
                1 if allow_tier_cd else 0,
                overlap,
                result_channel_json or "{}",
                payload_template,
            ),
        )
        self._conn.commit()
        loaded = self.get_job(jid)
        if loaded is None:
            msg = f"insert failed for job_id={jid}"
            raise ValueError(msg)
        return loaded

    def patch_job(
        self,
        job_id: str,
        *,
        enabled: bool | None = None,
        cron_expr: str | None = None,
        timezone: str | None = None,
        jitter_s: int | None = None,
        routing_mode: RoutingMode | None = None,
        delivery_mode: DeliveryMode | None = None,
        permission_template_ref: str | None = None,
        allow_tier_cd: bool | None = None,
        overlap_policy: str | None = None,
        result_channel_json: str | None = None,
        payload_template: str | None = None,
        next_fire_at_ns: int | None = None,
        recompute_schedule: bool = False,
    ) -> CronJobDetail:
        """Update fields on an existing cron job.

        Args:
            job_id (str): Primary key to patch.
            enabled (bool | None, optional): New enabled flag.
            cron_expr (str | None, optional): New cron expression.
            timezone (str | None, optional): New IANA zone.
            jitter_s (int | None, optional): New jitter seconds.
            routing_mode (RoutingMode | None, optional): New routing mode.
            delivery_mode (DeliveryMode | None, optional): New delivery mode.
            permission_template_ref (str | None, optional): New template ref.
            allow_tier_cd (bool | None, optional): Tier C/D allowance.
            overlap_policy (str | None, optional): New overlap policy.
            result_channel_json (str | None, optional): New result channel JSON.
            payload_template (str | None, optional): New payload template.
            next_fire_at_ns (int | None, optional): Explicit next fire override.
            recompute_schedule (bool, optional): When ``True`` and cron/tz changed, bump schedule.

        Returns:
            CronJobDetail: Updated row.

        Raises:
            ValueError: When the job is missing or cron expression is invalid.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> store = SqliteCronStore(c)
            >>> _ = store.insert_job(job_id="demo", cron_expr="0 12 * * *")
            >>> store.patch_job("demo", payload_template="updated").payload_template
            'updated'
        """
        current = self.get_job(job_id)
        if current is None:
            msg = f"unknown job_id: {job_id}"
            raise ValueError(msg)
        new_expr = _validate_cron_expr(cron_expr) if cron_expr is not None else current.cron_expr
        new_tz = timezone.strip() if timezone is not None else current.timezone
        schedule_changed = cron_expr is not None or timezone is not None
        nxt = current.next_fire_at_ns
        if next_fire_at_ns is not None:
            nxt = int(next_fire_at_ns)
        elif recompute_schedule or schedule_changed:
            nxt = compute_next_fire_ns(
                cron_expr=new_expr,
                tz_name=new_tz,
                from_ns=time.time_ns(),
            )
        self._conn.execute(
            """
            UPDATE trigger_cron_jobs SET
                enabled = ?,
                cron_expr = ?,
                timezone = ?,
                next_fire_at_ns = ?,
                jitter_s = ?,
                routing_mode = ?,
                delivery_mode = ?,
                permission_template_ref = ?,
                allow_tier_cd = ?,
                overlap_policy = ?,
                result_channel_json = ?,
                payload_template = ?
            WHERE job_id = ?
            """,
            (
                1 if (enabled if enabled is not None else current.enabled) else 0,
                new_expr,
                new_tz or "UTC",
                nxt,
                int(jitter_s if jitter_s is not None else current.jitter_s),
                routing_mode if routing_mode is not None else current.routing_mode,
                delivery_mode if delivery_mode is not None else current.delivery_mode,
                (
                    permission_template_ref.strip()
                    if permission_template_ref is not None
                    else current.permission_template_ref
                ),
                1 if (allow_tier_cd if allow_tier_cd is not None else current.allow_tier_cd) else 0,
                (
                    _normalize_overlap_policy(overlap_policy)
                    if overlap_policy is not None
                    else current.overlap_policy
                ),
                result_channel_json
                if result_channel_json is not None
                else current.result_channel_json,
                payload_template if payload_template is not None else current.payload_template,
                job_id.strip(),
            ),
        )
        self._conn.commit()
        loaded = self.get_job(job_id)
        if loaded is None:
            msg = f"patch failed for job_id={job_id}"
            raise ValueError(msg)
        return loaded

    def delete_job(self, job_id: str) -> bool:
        """Delete a cron job row.

        Args:
            job_id (str): Primary key.

        Returns:
            bool: ``True`` when a row was removed.

        Examples:
            >>> import sqlite3
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.triggers.cron import SqliteCronStore
            >>> c = sqlite3.connect(":memory:")
            >>> apply_migrations(c)
            >>> store = SqliteCronStore(c)
            >>> _ = store.insert_job(job_id="demo", cron_expr="0 12 * * *")
            >>> store.delete_job("demo")
            True
        """
        cur = self._conn.execute(
            "DELETE FROM trigger_cron_jobs WHERE job_id = ?",
            (job_id.strip(),),
        )
        self._conn.commit()
        return int(cur.rowcount) > 0


def list_cron_jobs(conn: sqlite3.Connection) -> list[CronJobDetail]:
    """List all cron jobs in workspace ``sevn.db``.

    Args:
        conn (sqlite3.Connection): Migrated workspace database handle.

    Returns:
        list[CronJobDetail]: All persisted jobs.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron import list_cron_jobs
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> list_cron_jobs(c)
        []
    """
    return SqliteCronStore(conn).list_jobs()


def add_cron_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    cron_expr: str,
    timezone: str = "UTC",
    enabled: bool = True,
    jitter_s: int = 0,
    routing_mode: RoutingMode = "fixed",
    delivery_mode: DeliveryMode = "agent_pass",
    permission_template_ref: str = "default",
    allow_tier_cd: bool = False,
    overlap_policy: str = "skip",
    result_channel_json: str = "{}",
    payload_template: str | None = None,
    next_fire_at_ns: int | None = None,
) -> CronJobDetail:
    """Insert a cron job (scheduling skill façade).

    Args:
        conn (sqlite3.Connection): Migrated workspace database handle.
        job_id (str): Primary key.
        cron_expr (str): Five-field cron schedule.
        timezone (str, optional): IANA zone. Defaults to ``UTC``.
        enabled (bool, optional): Active flag. Defaults to ``True``.
        jitter_s (int, optional): Jitter seconds. Defaults to ``0``.
        routing_mode (RoutingMode, optional): Routing mode. Defaults to ``fixed``.
        delivery_mode (DeliveryMode, optional): Delivery mode. Defaults to ``agent_pass``.
        permission_template_ref (str, optional): Template ref. Defaults to ``default``.
        allow_tier_cd (bool, optional): Tier C/D allowance. Defaults to ``False``.
        overlap_policy (str, optional): Overlap policy. Defaults to ``skip``.
        result_channel_json (str, optional): Serialised result channel.
        payload_template (str | None, optional): Prompt or notify body.
        next_fire_at_ns (int | None, optional): First-fire override.

    Returns:
        CronJobDetail: Inserted row.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron import add_cron_job
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> add_cron_job(c, job_id="x", cron_expr="0 9 * * *").job_id
        'x'
    """
    return SqliteCronStore(conn).insert_job(
        job_id=job_id,
        cron_expr=cron_expr,
        timezone=timezone,
        enabled=enabled,
        jitter_s=jitter_s,
        routing_mode=routing_mode,
        delivery_mode=delivery_mode,
        permission_template_ref=permission_template_ref,
        allow_tier_cd=allow_tier_cd,
        overlap_policy=overlap_policy,
        result_channel_json=result_channel_json,
        payload_template=payload_template,
        next_fire_at_ns=next_fire_at_ns,
    )


def edit_cron_job(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    enabled: bool | None = None,
    cron_expr: str | None = None,
    timezone: str | None = None,
    jitter_s: int | None = None,
    routing_mode: RoutingMode | None = None,
    delivery_mode: DeliveryMode | None = None,
    permission_template_ref: str | None = None,
    allow_tier_cd: bool | None = None,
    overlap_policy: str | None = None,
    result_channel_json: str | None = None,
    payload_template: str | None = None,
    next_fire_at_ns: int | None = None,
    recompute_schedule: bool = False,
) -> CronJobDetail:
    """Patch a cron job (scheduling skill façade).

    Args:
        conn (sqlite3.Connection): Migrated workspace database handle.
        job_id (str): Primary key.
        enabled (bool | None, optional): New enabled flag.
        cron_expr (str | None, optional): New cron expression.
        timezone (str | None, optional): New IANA zone.
        jitter_s (int | None, optional): New jitter seconds.
        routing_mode (RoutingMode | None, optional): New routing mode.
        delivery_mode (DeliveryMode | None, optional): New delivery mode.
        permission_template_ref (str | None, optional): New template ref.
        allow_tier_cd (bool | None, optional): Tier C/D allowance.
        overlap_policy (str | None, optional): New overlap policy.
        result_channel_json (str | None, optional): New result channel JSON.
        payload_template (str | None, optional): New payload template.
        next_fire_at_ns (int | None, optional): Next fire override.
        recompute_schedule (bool, optional): Recompute next fire from cron/tz.

    Returns:
        CronJobDetail: Updated row.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron import add_cron_job, edit_cron_job
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = add_cron_job(c, job_id="x", cron_expr="0 9 * * *")
        >>> edit_cron_job(c, job_id="x", enabled=False).enabled
        False
    """
    return SqliteCronStore(conn).patch_job(
        job_id,
        enabled=enabled,
        cron_expr=cron_expr,
        timezone=timezone,
        jitter_s=jitter_s,
        routing_mode=routing_mode,
        delivery_mode=delivery_mode,
        permission_template_ref=permission_template_ref,
        allow_tier_cd=allow_tier_cd,
        overlap_policy=overlap_policy,
        result_channel_json=result_channel_json,
        payload_template=payload_template,
        next_fire_at_ns=next_fire_at_ns,
        recompute_schedule=recompute_schedule,
    )


def delete_cron_job(conn: sqlite3.Connection, job_id: str) -> bool:
    """Delete a cron job (scheduling skill façade).

    Args:
        conn (sqlite3.Connection): Migrated workspace database handle.
        job_id (str): Primary key.

    Returns:
        bool: ``True`` when a row was removed.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron import add_cron_job, delete_cron_job
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = add_cron_job(c, job_id="x", cron_expr="0 9 * * *")
        >>> delete_cron_job(c, "x")
        True
    """
    return SqliteCronStore(conn).delete_job(job_id)


def _parse_reminder_at(at: str, tz_name: str) -> datetime:
    """Parse an ISO-8601 reminder timestamp in the given zone.

    Args:
        at (str): ISO datetime (``Z`` suffix allowed).
        tz_name (str): IANA zone when ``at`` is naive.

    Returns:
        datetime: Timezone-aware instant.

    Raises:
        ValueError: When parsing fails or the instant is in the past.

    Examples:
        >>> from sevn.triggers.cron import _parse_reminder_at
        >>> dt = _parse_reminder_at("2030-06-15T14:30:00", "UTC")
        >>> dt.year
        2030
    """
    raw = at.strip()
    if not raw:
        msg = "at must be non-empty"
        raise ValueError(msg)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        msg = f"invalid at datetime: {at}"
        raise ValueError(msg) from exc
    tz = ZoneInfo(tz_name or "UTC")
    parsed = parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)
    if int(parsed.timestamp() * 1e9) <= time.time_ns():
        msg = "reminder at must be in the future"
        raise ValueError(msg)
    return parsed


def add_reminder(
    conn: sqlite3.Connection,
    *,
    at: str,
    prompt: str,
    job_id: str | None = None,
    timezone: str = "UTC",
    delivery_mode: DeliveryMode = "agent_pass",
    permission_template_ref: str = "default",
    result_channel_json: str = "{}",
) -> CronJobDetail:
    """Insert a one-shot reminder as a cron row firing at ``at``.

    Args:
        conn (sqlite3.Connection): Migrated workspace database handle.
        at (str): ISO-8601 fire time (future).
        prompt (str): Agent or notify body.
        job_id (str | None, optional): Primary key; auto-generated when omitted.
        timezone (str, optional): IANA zone for naive ``at``. Defaults to ``UTC``.
        delivery_mode (DeliveryMode, optional): Delivery mode. Defaults to ``agent_pass``.
        permission_template_ref (str, optional): Template ref. Defaults to ``default``.
        result_channel_json (str, optional): Serialised result channel.

    Returns:
        CronJobDetail: Inserted reminder row.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> from sevn.triggers.cron import add_reminder
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> job = add_reminder(
        ...     c, at="2030-06-15T14:30:00", prompt="stand up", job_id="reminder_test",
        ... )
        >>> job.job_id
        'reminder_test'
    """
    tz = (timezone or "UTC").strip() or "UTC"
    when = _parse_reminder_at(at, tz)
    jid = (job_id or f"reminder_{uuid.uuid4().hex[:12]}").strip()
    cron_expr = f"{when.minute} {when.hour} {when.day} {when.month} *"
    fire_ns = int(when.timestamp() * 1e9)
    return add_cron_job(
        conn,
        job_id=jid,
        cron_expr=cron_expr,
        timezone=tz,
        delivery_mode=delivery_mode,
        permission_template_ref=permission_template_ref,
        result_channel_json=result_channel_json,
        payload_template=prompt.strip() or None,
        next_fire_at_ns=fire_ns,
    )


def compute_next_fire_ns(*, cron_expr: str, tz_name: str, from_ns: int) -> int:
    """Return the next scheduled instant strictly after ``from_ns``.
    Args:
        cron_expr (str): Five-field cron expression for ``croniter``.
        tz_name (str): IANA zone for the iterator (falls back to ``UTC``).
        from_ns (int): Reference instant in nanoseconds since UNIX epoch.
    Returns:
        int: **Exclusive** next fire time in nanoseconds.
    Examples:
        >>> from sevn.triggers.cron import compute_next_fire_ns
        >>> ns = compute_next_fire_ns(
        ...     cron_expr="0 * * * *", tz_name="UTC", from_ns=1_700_000_000_000_000_000,
        ... )
        >>> isinstance(ns, int) and ns > 1_700_000_000_000_000_000
        True
    """
    tz = ZoneInfo(tz_name or "UTC")
    base = datetime.fromtimestamp(from_ns / 1e9, tz=UTC).astimezone(tz)
    it = croniter(cron_expr, base)
    nxt = it.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=tz)
    return int(nxt.timestamp() * 1e9)


async def cron_tick(
    *,
    cron_store: SqliteCronStore,
    workspace: WorkspaceConfig,
    content_root: Path,
    trace: TraceSink,
    dispatch: Callable[[DispatchRequest], Coroutine[Any, Any, None]],
) -> None:
    """Load due cron rows, invoke ``dispatch`` for each, and bump schedules.
    When ``triggers.paused`` is set, emits ``trigger.paused`` and returns without work.
    Args:
        cron_store (SqliteCronStore): Persistence for ``trigger_cron_jobs``.
        workspace (WorkspaceConfig): Workspace (pause flag).
        content_root (Path): Passed through to dispatch (inbox, secrets).
        trace (TraceSink): Gateway trace sink.
        dispatch (Callable): Async callable taking :class:`~sevn.triggers.request.DispatchRequest`.
    Examples:
        >>> import inspect
        >>> from sevn.triggers.cron import cron_tick
        >>> inspect.iscoroutinefunction(cron_tick)
        True
    """
    if workspace.triggers and workspace.triggers.paused:
        await trace.emit(
            TraceEvent(
                kind="trigger.paused",
                span_id=str(uuid.uuid4()),
                parent_span_id=None,
                session_id="trigger",
                turn_id="cron",
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status="skipped",
                attrs={"transport": "cron"},
            ),
        )
        return
    now_ns = time.time_ns()
    due = cron_store.list_due(now_ns)

    def _bump_schedule(*, job_id: str, cron_expr: str, tz_name: str, status: str) -> None:
        nxt = compute_next_fire_ns(
            cron_expr=cron_expr,
            tz_name=tz_name,
            from_ns=time.time_ns(),
        )
        cron_store.update_schedule(
            job_id=job_id,
            next_fire_at_ns=nxt,
            last_correlation_id=correlation_id,
            last_status=status,
        )

    for row in due:
        correlation_id = str(uuid.uuid4())
        handler = _CRON_JOB_HANDLERS.get(row.job_id)
        if handler is not None:
            try:
                # Sync handlers (e.g. issue-watch ``gh`` / subprocess) must not
                # block the gateway event loop.
                await asyncio.to_thread(handler, workspace=content_root)
                _bump_schedule(
                    job_id=row.job_id,
                    cron_expr=row.cron_expr,
                    tz_name=row.timezone,
                    status="ok",
                )
            except Exception:
                logger.exception("cron_handler_failed job_id={}", row.job_id)
                _bump_schedule(
                    job_id=row.job_id,
                    cron_expr=row.cron_expr,
                    tz_name=row.timezone,
                    status="error",
                )
            continue
        try:
            rc_data = json.loads(row.result_channel_json)
            rc = ResultChannel.model_validate(rc_data)
        except Exception:
            rc = ResultChannel(kind="LOG")
        prompt = row.payload_template or f"cron job {row.job_id}"
        req = DispatchRequest(
            prompt=prompt,
            routing_mode=row.routing_mode,
            delivery_mode=row.delivery_mode,
            permission_template_ref=row.permission_template_ref,
            allow_tier_cd=row.allow_tier_cd,
            result_channel=rc,
            correlation_id=correlation_id,
            trigger_meta={
                "transport": "cron",
                "cron_job_id": row.job_id,
                "overlap_policy": row.overlap_policy,
                "scope": "default",
            },
            notify_template=row.payload_template if row.delivery_mode == "notify_only" else None,
        )
        try:
            await asyncio.wait_for(dispatch(req), timeout=600.0)
            _bump_schedule(
                job_id=row.job_id,
                cron_expr=row.cron_expr,
                tz_name=row.timezone,
                status="ok",
            )
        except Exception:
            logger.exception("cron_job_dispatch_failed job_id={}", row.job_id)
            _bump_schedule(
                job_id=row.job_id,
                cron_expr=row.cron_expr,
                tz_name=row.timezone,
                status="error",
            )
