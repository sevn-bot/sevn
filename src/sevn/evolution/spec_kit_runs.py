"""Append-only spec-kit run audit log (`specs/35-bot-evolution.md`).

Module: sevn.evolution.spec_kit_runs
Depends: dataclasses, json, pathlib, uuid, datetime

Exports:
    SpecKitRunRecord — one subprocess audit row.
    append_spec_kit_run — write a run record under ``workspace/.sevn/spec-kit/``.
    list_spec_kit_runs — read recent runs newest-first.
    new_run_id — generate a run id.
    utc_now_iso — UTC timestamp helper.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime audit log paths
from typing import Literal

SpecKitRunStatus = Literal["ok", "error", "dry_run", "rejected"]


@dataclass(frozen=True)
class SpecKitRunRecord:
    """One allowlisted spec-kit subprocess invocation."""

    run_id: str
    command: str
    argv: list[str]
    cwd: str
    status: SpecKitRunStatus
    started_at: str
    finished_at: str
    owner_principal: str
    issue_id: str | None = None
    job_id: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    detail: str | None = None


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form.

    Returns:
        str: Timestamp string.

    Examples:
        >>> "T" in utc_now_iso()
        True
    """
    return datetime.now(tz=UTC).isoformat()


def new_run_id() -> str:
    """Generate a new spec-kit run identifier.

    Returns:
        str: Hex uuid without dashes.

    Examples:
        >>> len(new_run_id()) >= 32
        True
    """
    return uuid.uuid4().hex


def _runs_path(dot_sevn: Path) -> Path:
    """Return the JSONL audit path under ``.sevn/spec-kit/``.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.

    Returns:
        Path: ``runs.jsonl`` file path.

    Examples:
        >>> _runs_path(Path("/w/.sevn")).name
        'runs.jsonl'
    """
    return dot_sevn / "spec-kit" / "runs.jsonl"


def append_spec_kit_run(dot_sevn: Path, record: SpecKitRunRecord) -> None:
    """Append one audit row to ``runs.jsonl``.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        record (SpecKitRunRecord): Row to persist.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> dot = Path(tempfile.mkdtemp()) / ".sevn"
        >>> dot.mkdir(parents=True)
        >>> rec = SpecKitRunRecord(
        ...     run_id="r1",
        ...     command="plan",
        ...     argv=[],
        ...     cwd="/tmp",
        ...     status="dry_run",
        ...     started_at="t0",
        ...     finished_at="t1",
        ...     owner_principal="owner",
        ... )
        >>> append_spec_kit_run(dot, rec)
        >>> _runs_path(dot).is_file()
        True
    """
    path = _runs_path(dot_sevn)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def list_spec_kit_runs(
    dot_sevn: Path,
    *,
    limit: int = 50,
    cursor: str | None = None,
    issue_id: str | None = None,
    job_id: str | None = None,
) -> tuple[list[dict[str, object]], str | None]:
    """Return recent spec-kit runs newest-first.

    Args:
        dot_sevn (Path): Workspace ``.sevn`` directory.
        limit (int): Maximum rows.
        cursor (str | None): Optional pagination cursor (run_id).
        issue_id (str | None): When set, only rows matching this evolution issue id.
        job_id (str | None): When set, only rows matching this self-improve job id.

    Returns:
        tuple[list[dict[str, object]], str | None]: Items and optional next cursor.

    Examples:
        >>> list_spec_kit_runs(Path("/nonexistent/.sevn"), limit=5)[0]
        []
    """
    path = _runs_path(dot_sevn)
    if not path.is_file():
        return [], None
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    rows: list[dict[str, object]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if issue_id is not None and str(row.get("issue_id", "")) != issue_id:
            continue
        if job_id is not None and str(row.get("job_id", "")) != job_id:
            continue
        if cursor and str(row.get("run_id", "")) >= cursor:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    next_cursor = str(rows[-1].get("run_id")) if len(rows) >= limit and rows else None
    return rows[:limit], next_cursor


__all__ = [
    "SpecKitRunRecord",
    "SpecKitRunStatus",
    "append_spec_kit_run",
    "list_spec_kit_runs",
    "new_run_id",
    "utc_now_iso",
]
