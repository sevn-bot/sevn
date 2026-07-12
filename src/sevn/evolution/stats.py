"""Evolution Mission Control roll-up stats (`specs/35-bot-evolution.md` §2.8).

Module: sevn.evolution.stats
Depends: json, sqlite3, sevn.evolution.issues

Exports:
    compute_evolution_stats — aggregate issue, PR, eval, and sync counters.
    last_sync_path — resolve last sync marker path.
    load_last_sync_record — read last ``sevn sync`` marker when present.
    record_last_sync — persist a last-sync marker.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TC003 — runtime eval stats queries
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.evolution.issues import list_issues

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout


def last_sync_path(layout: WorkspaceLayout) -> Path:
    """Return path to the last sync marker JSON.

    Args:
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        Path: ``.sevn/evolution/last_sync.json``.

    Examples:
        >>> last_sync_path.__name__
        'last_sync_path'
    """
    return layout.dot_sevn / "evolution" / "last_sync.json"


def load_last_sync_record(layout: WorkspaceLayout) -> dict[str, Any] | None:
    """Load last ``sevn sync`` metadata when the marker file exists.

    Args:
        layout (WorkspaceLayout): Workspace layout.

    Returns:
        dict[str, Any] | None: Parsed marker or ``None``.

    Examples:
        >>> load_last_sync_record.__name__
        'load_last_sync_record'
    """
    path = last_sync_path(layout)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def record_last_sync(
    layout: WorkspaceLayout, *, status: str = "ok", detail: str = ""
) -> dict[str, Any]:
    """Persist a last-sync marker (used by sync cron and tests).

    Args:
        layout (WorkspaceLayout): Workspace layout.
        status (str): Outcome label.
        detail (str): Optional detail text.

    Returns:
        dict[str, Any]: Written marker body.

    Examples:
        >>> record_last_sync.__name__
        'record_last_sync'
    """
    from sevn.evolution.issues import utc_now_iso

    marker = {
        "status": status,
        "detail": detail,
        "completed_at": utc_now_iso(),
    }
    path = last_sync_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker, indent=2, sort_keys=True), encoding="utf-8")
    return marker


def _eval_pass_rate(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute eval pass rate from improve jobs with eval reports.

    Args:
        conn (sqlite3.Connection): Workspace SQLite.

    Returns:
        dict[str, Any]: ``total``, ``passed``, ``pass_rate`` fields.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> stats = _eval_pass_rate(c)
        >>> stats["total"]
        0
        >>> c.close()
    """
    rows = conn.execute(
        """SELECT eval_report_path FROM self_improve_jobs
           WHERE eval_report_path IS NOT NULL AND eval_report_path != ''""",
    ).fetchall()
    total = 0
    passed = 0
    for (report_path,) in rows:
        path = Path(str(report_path))
        if not path.is_file():
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict):
            continue
        total += 1
        if report.get("passed") is True:
            passed += 1
    rate = (passed / total) if total else None
    return {"total": total, "passed": passed, "pass_rate": rate}


def compute_evolution_stats(
    layout: WorkspaceLayout,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Aggregate evolution dashboard counters.

    Args:
        layout (WorkspaceLayout): Workspace layout.
        conn (sqlite3.Connection): Workspace SQLite for improve-job eval stats.

    Returns:
        dict[str, Any]: Stats payload for ``GET /api/v1/evolution/stats``.

    Examples:
        >>> compute_evolution_stats.__name__
        'compute_evolution_stats'
    """
    issues = list_issues(layout, limit=500)
    open_count = sum(1 for issue in issues if issue.state not in ("done", "cancelled"))
    closed_count = sum(1 for issue in issues if issue.state == "done")
    pr_count = sum(1 for issue in issues if issue.pr_url)
    last_sync = load_last_sync_record(layout)
    eval_stats = _eval_pass_rate(conn)
    return {
        "issues_open": open_count,
        "issues_closed": closed_count,
        "issues_total": len(issues),
        "prs": pr_count,
        "eval": eval_stats,
        "last_sync": last_sync,
    }


__all__ = [
    "compute_evolution_stats",
    "last_sync_path",
    "load_last_sync_record",
    "record_last_sync",
]
