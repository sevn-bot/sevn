"""Canonical paths for workspace SQLite files.

Module: sevn.storage.paths

Exports:
    sevn_db_path — main application database under ``.sevn``.
    traces_sqlite_path — optional Mission Control trace DB (schema in spec 04).
    turn_bundles_dir — per-turn diagnostic JSONL root under ``.sevn/turns``.
    turn_bundle_day_slug — ``DDMMYY`` folder name from a first-seen UTC timestamp.
    is_turn_bundle_day_slug — whether a directory name is a day partition slug.
    turn_bundle_day_dir — one day's bundle folder under ``.sevn/turns/<DDMMYY>``.
    turn_bundle_index_path — ``index.json`` beside bundle ``*.jsonl`` files.
    turn_bundle_file_path — one turn's ``<safe_turn_id>.jsonl`` path.

Examples:
    >>> from pathlib import Path
    >>> sevn_db_path(Path("/w/.sevn")) == Path("/w/.sevn/sevn.db")
    True
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def sevn_db_path(dot_sevn: Path) -> Path:
    """Return the path to ``sevn.db`` under the workspace ``.sevn`` directory.

        Args:
    dot_sevn (Path): Resolved ``WorkspaceLayout.dot_sevn``.

        Returns:
    Path: Absolute or relative path ending with ``sevn.db``.

        Examples:
            >>> from pathlib import Path
            >>> sevn_db_path(Path("/w/.sevn")) == Path("/w/.sevn/sevn.db")
            True
    """
    return dot_sevn / "sevn.db"


def traces_sqlite_path(dot_sevn: Path) -> Path:
    """Return the path to ``traces.db`` (SQLite trace sink) under ``.sevn``.

        Args:
    dot_sevn (Path): Resolved ``WorkspaceLayout.dot_sevn``.

        Returns:
    Path: Path ending with ``traces.db`` (DDL owned by tracing spec).

        Note:
            Schema and migrations for this file land in ``specs/04-tracing.md``.

        Examples:
            >>> from pathlib import Path
            >>> traces_sqlite_path(Path("/z/.sevn")).name
            'traces.db'
    """
    return dot_sevn / "traces.db"


def turn_bundles_dir(dot_sevn: Path) -> Path:
    """Return ``<content_root>/.sevn/turns`` (sibling of ``traces/`` and ``traces.db``).

        Args:
    dot_sevn (Path): Resolved ``WorkspaceLayout.dot_sevn``.

        Returns:
    Path: Root directory holding per-day ``<DDMMYY>/`` subfolders (and optional
        legacy flat ``*.jsonl`` + root ``index.json``).

        Examples:
            >>> from pathlib import Path
            >>> turn_bundles_dir(Path("/w/.sevn")) == Path("/w/.sevn/turns")
            True
    """
    return dot_sevn / "turns"


def turn_bundle_day_slug(first_seen_at: str) -> str:
    """Return ``DDMMYY`` day folder name from a first-seen UTC timestamp.

    Day assignment uses the UTC calendar day of the turn's first-seen timestamp
    (ISO-8601 from bundle meta ``created_at``, message ``MIN(created_at)``, or
    export candidate ``first_seen_at``).

        Args:
    first_seen_at (str): ISO-8601 timestamp (timezone-aware or naive UTC).

        Returns:
    str: Six-digit day slug, e.g. ``160626`` for 16 Jun 2026 UTC.

        Examples:
            >>> turn_bundle_day_slug("2026-06-16T00:00:01+00:00")
            '160626'
            >>> turn_bundle_day_slug("2026-06-15T10:00:00+00:00")
            '150626'
    """
    normalized = first_seen_at.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%d%m%y")


def is_turn_bundle_day_slug(name: str) -> bool:
    """Return whether ``name`` is a day-partition folder slug (``DDMMYY``).

        Args:
    name (str): Directory basename under ``.sevn/turns``.

        Returns:
    bool: ``True`` when ``name`` is six decimal digits.

        Examples:
            >>> is_turn_bundle_day_slug("160626")
            True
            >>> is_turn_bundle_day_slug("index.json")
            False
    """
    return len(name) == 6 and name.isdigit()


def turn_bundle_day_dir(turns_root: Path, day_slug: str) -> Path:
    """Return one day's bundle folder under ``.sevn/turns/<DDMMYY>``.

        Args:
    turns_root (Path): Resolved :func:`turn_bundles_dir` path.
    day_slug (str): Day partition from :func:`turn_bundle_day_slug`.

        Returns:
    Path: Directory holding that day's ``index.json`` and ``*.jsonl`` files.

        Examples:
            >>> from pathlib import Path
            >>> turn_bundle_day_dir(Path("/w/.sevn/turns"), "160626")
            PosixPath('/w/.sevn/turns/160626')
    """
    return turns_root / day_slug


def turn_bundle_index_path(bundles_dir: Path) -> Path:
    """Return ``index.json`` under a turn-bundles directory.

        Args:
    bundles_dir (Path): Day folder (``turns/<DDMMYY>``) or legacy flat ``turns/`` root.

        Returns:
    Path: Index file tracking bundle metadata and ``processed`` flags.

        Examples:
            >>> from pathlib import Path
            >>> turn_bundle_index_path(Path("/w/.sevn/turns/160626")).name
            'index.json'
    """
    return bundles_dir / "index.json"


def turn_bundle_file_path(bundles_dir: Path, safe_turn_id: str) -> Path:
    """Return the JSONL path for one turn bundle file.

        Args:
    bundles_dir (Path): Day folder or legacy flat ``turns/`` root.
    safe_turn_id (str): Filesystem-safe slug from :func:`sevn.gateway.turn_bundle.safe_turn_id`.

        Returns:
    Path: ``<bundles_dir>/<safe_turn_id>.jsonl``.

        Examples:
            >>> from pathlib import Path
            >>> turn_bundle_file_path(Path("/w/.sevn/turns/160626"), "telegram_user_1").suffix
            '.jsonl'
    """
    return bundles_dir / f"{safe_turn_id}.jsonl"
