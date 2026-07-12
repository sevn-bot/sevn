"""SQLite persistence for Cursor cloud agent jobs.

Module: sevn.integrations.cursor_cloud.jobs
Depends: sqlite3, uuid, datetime

Exports:
    CursorCloudJob — persisted job record.
    insert_job — create a local job row.
    get_job — fetch by job_id or cursor_agent_id.
    update_job — patch status fields.
    list_workspace_jobs — list recent jobs.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class CursorCloudJob:
    """One persisted cloud agent delegation.

    Attributes:
        job_id (str): Local UUID.
        cursor_agent_id (str): Cursor ``bc-`` id.
        latest_run_id (str | None): Latest run id when known.
        session_key (str): Originating session.
        prompt (str): Task prompt text.
        repo_url (str): Target repository URL.
        starting_ref (str): Git starting ref.
        status (str): Last known status.
        pr_url (str | None): Pull request URL when available.
        branch (str | None): Pushed branch name.
        agent_url (str | None): Dashboard URL.
        result_text (str | None): Terminal run summary.
        artifact_count (int): Cached artifact list size.
        error_message (str | None): Last error detail.
        created_at (str): ISO timestamp.
        updated_at (str): ISO timestamp.
    """

    job_id: str
    cursor_agent_id: str
    latest_run_id: str | None
    session_key: str
    prompt: str
    repo_url: str
    starting_ref: str
    status: str
    pr_url: str | None
    branch: str | None
    agent_url: str | None
    result_text: str | None
    artifact_count: int
    error_message: str | None
    created_at: str
    updated_at: str


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string.

    Returns:
        str: ISO-8601 timestamp.

    Examples:
        >>> "T" in _now_iso()
        True
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _row_to_job(row: sqlite3.Row) -> CursorCloudJob:
    """Map a SQLite row to :class:`CursorCloudJob`.

    Args:
        row (sqlite3.Row): Query row.

    Returns:
        CursorCloudJob: Parsed job.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> _ensure_row_factory(conn)
        >>> isinstance(conn.row_factory, type(sqlite3.Row))
        True
    """
    return CursorCloudJob(
        job_id=str(row["job_id"]),
        cursor_agent_id=str(row["cursor_agent_id"]),
        latest_run_id=row["latest_run_id"],
        session_key=str(row["session_key"] or ""),
        prompt=str(row["prompt"]),
        repo_url=str(row["repo_url"]),
        starting_ref=str(row["starting_ref"]),
        status=str(row["status"]),
        pr_url=row["pr_url"],
        branch=row["branch"],
        agent_url=row["agent_url"],
        result_text=row["result_text"],
        artifact_count=int(row["artifact_count"] or 0),
        error_message=row["error_message"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _ensure_row_factory(conn: sqlite3.Connection) -> None:
    """Set ``sqlite3.Row`` factory when not already configured.

    Args:
        conn (sqlite3.Connection): Connection to configure.

    Examples:
        >>> import sqlite3
        >>> c = sqlite3.connect(":memory:")
        >>> _ensure_row_factory(c)
        >>> c.row_factory is sqlite3.Row
        True
    """
    if conn.row_factory is None:
        conn.row_factory = sqlite3.Row


def insert_job(
    conn: sqlite3.Connection,
    *,
    cursor_agent_id: str,
    session_key: str,
    prompt: str,
    repo_url: str,
    starting_ref: str,
    status: str,
    agent_url: str | None = None,
    latest_run_id: str | None = None,
) -> CursorCloudJob:
    """Insert a new job row.

    Args:
        conn (sqlite3.Connection): Workspace DB connection.
        cursor_agent_id (str): Cursor agent id.
        session_key (str): Session key for attribution.
        prompt (str): Task prompt.
        repo_url (str): Repository URL.
        starting_ref (str): Git ref.
        status (str): Initial status string.
        agent_url (str | None): Dashboard URL.
        latest_run_id (str | None): Run id when known at create time.

    Returns:
        CursorCloudJob: Inserted job record.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> job = insert_job(
        ...     c,
        ...     cursor_agent_id="bc-1",
        ...     session_key="s",
        ...     prompt="fix",
        ...     repo_url="https://github.com/o/r",
        ...     starting_ref="main",
        ...     status="ACTIVE",
        ... )
        >>> job.cursor_agent_id
        'bc-1'
    """
    _ensure_row_factory(conn)
    job_id = str(uuid.uuid4())
    ts = _now_iso()
    conn.execute(
        """
        INSERT INTO cursor_cloud_jobs (
            job_id, cursor_agent_id, latest_run_id, session_key, prompt,
            repo_url, starting_ref, status, pr_url, branch, agent_url,
            result_text, artifact_count, error_message, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, 0, NULL, ?, ?)
        """,
        (
            job_id,
            cursor_agent_id,
            latest_run_id,
            session_key,
            prompt,
            repo_url,
            starting_ref,
            status,
            agent_url,
            ts,
            ts,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM cursor_cloud_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        msg = f"cursor_cloud_jobs insert failed for job_id={job_id}"
        raise RuntimeError(msg)
    return _row_to_job(row)


def get_job(
    conn: sqlite3.Connection,
    *,
    job_id: str | None = None,
    cursor_agent_id: str | None = None,
) -> CursorCloudJob | None:
    """Fetch one job by local id or Cursor agent id.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        job_id (str | None): Local job UUID.
        cursor_agent_id (str | None): Cursor ``bc-`` id.

    Returns:
        CursorCloudJob | None: Job when found.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> get_job(c, job_id="missing") is None
        True
    """
    _ensure_row_factory(conn)
    if job_id:
        row = conn.execute(
            "SELECT * FROM cursor_cloud_jobs WHERE job_id = ?",
            (job_id.strip(),),
        ).fetchone()
        return _row_to_job(row) if row else None
    if cursor_agent_id:
        row = conn.execute(
            "SELECT * FROM cursor_cloud_jobs WHERE cursor_agent_id = ? ORDER BY created_at DESC LIMIT 1",
            (cursor_agent_id.strip(),),
        ).fetchone()
        return _row_to_job(row) if row else None
    return None


def update_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str | None = None,
    latest_run_id: str | None = None,
    pr_url: str | None = None,
    branch: str | None = None,
    agent_url: str | None = None,
    result_text: str | None = None,
    artifact_count: int | None = None,
    error_message: str | None = None,
) -> CursorCloudJob | None:
    """Patch mutable fields on a job row.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        job_id (str): Local job id.
        status (str | None): New status.
        latest_run_id (str | None): Run id.
        pr_url (str | None): PR URL.
        branch (str | None): Branch name.
        agent_url (str | None): Dashboard URL.
        result_text (str | None): Run result text.
        artifact_count (int | None): Artifact count cache.
        error_message (str | None): Error detail.

    Returns:
        CursorCloudJob | None: Updated job or ``None`` when missing.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> j = insert_job(
        ...     c,
        ...     cursor_agent_id="bc-2",
        ...     session_key="",
        ...     prompt="p",
        ...     repo_url="https://github.com/a/b",
        ...     starting_ref="main",
        ...     status="ACTIVE",
        ... )
        >>> updated = update_job(c, j.job_id, status="FINISHED")
        >>> updated is not None and updated.status == "FINISHED"
        True
    """
    fields: list[str] = []
    values: list[Any] = []
    mapping = {
        "status": status,
        "latest_run_id": latest_run_id,
        "pr_url": pr_url,
        "branch": branch,
        "agent_url": agent_url,
        "result_text": result_text,
        "artifact_count": artifact_count,
        "error_message": error_message,
    }
    for col, val in mapping.items():
        if val is not None:
            fields.append(f"{col} = ?")
            values.append(val)
    _ensure_row_factory(conn)
    if not fields:
        return get_job(conn, job_id=job_id)
    fields.append("updated_at = ?")
    values.append(_now_iso())
    values.append(job_id)
    conn.execute(
        f"UPDATE cursor_cloud_jobs SET {', '.join(fields)} WHERE job_id = ?",  # nosec B608 — fixed column assignments
        values,
    )
    conn.commit()
    return get_job(conn, job_id=job_id)


def list_workspace_jobs(
    conn: sqlite3.Connection,
    *,
    session_key: str | None = None,
    limit: int = 20,
) -> list[CursorCloudJob]:
    """List recent jobs, optionally filtered by session.

    Args:
        conn (sqlite3.Connection): Workspace DB.
        session_key (str | None): Filter key; ``None`` lists all.
        limit (int): Max rows.

    Returns:
        list[CursorCloudJob]: Newest first.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> list_workspace_jobs(c, limit=5)
        []
    """
    _ensure_row_factory(conn)
    cap = max(1, min(int(limit), 100))
    if session_key and session_key.strip():
        rows = conn.execute(
            """
            SELECT * FROM cursor_cloud_jobs
            WHERE session_key = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_key.strip(), cap),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM cursor_cloud_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cap,),
        ).fetchall()
    return [_row_to_job(r) for r in rows]
