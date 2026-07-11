"""Lightweight workspace layout validation on gateway boot.

Module: sevn.workspace.layout_validate
Depends: sevn.agent.tracing.sink, sevn.data.skills_index, sevn.workspace.layout

Exports:
    WorkspaceLayoutValidationResult — missing paths from a validation pass.
    validate_workspace_layout — filesystem check against canonical lists.
    validate_workspace_layout_at_boot — seed ``skills/INDEX.md`` + layout trace on boot.

Examples:
    >>> from pathlib import Path
    >>> from sevn.workspace.layout import WorkspaceLayout
    >>> from sevn.workspace.layout_validate import validate_workspace_layout
    >>> lay = WorkspaceLayout(Path("/nonexistent/sevn.json"), Path("/nonexistent"))
    >>> result = validate_workspace_layout(lay)
    >>> isinstance(result.missing_dirs, tuple)
    True
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from time import time_ns
from typing import TYPE_CHECKING, Final, Literal

from loguru import logger

from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.agent.tracing.sink import TraceSink
    from sevn.workspace.layout import WorkspaceLayout

CANONICAL_WORKSPACE_DIRS: Final[tuple[str, ...]] = (
    ".sevn",
    "logs",
    "memory",
    "sessions",
    "skills",
)

# Lazy-created operator dirs — absence at boot is expected, not a mismatch (P15).
_OPTIONAL_WORKSPACE_DIRS: Final[frozenset[str]] = frozenset({"memory", "sessions"})

CANONICAL_WORKSPACE_MD_FILES: Final[tuple[str, ...]] = (
    "AGENTS.md",
    "sevn.bot.md",
    "IDENTITY.md",
    "MEMORY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
    "WORKSPACE.md",
)

PathSeedStatus = Literal["created", "exists", "skipped"]


@dataclass(frozen=True)
class WorkspaceLayoutValidationResult:
    """Outcome of comparing ``content_root`` against canonical layout lists."""

    missing_dirs: tuple[str, ...]
    missing_files: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return ``True`` when every canonical path is present.

        Returns:
            bool: ``True`` when ``missing_dirs`` and ``missing_files`` are empty.

        Examples:
            >>> WorkspaceLayoutValidationResult((), ()).ok
            True
            >>> WorkspaceLayoutValidationResult(("logs",), ()).ok
            False
        """
        return not self.missing_dirs and not self.missing_files


def _log_canonical_path_status(
    *,
    rel_path: str,
    status: PathSeedStatus,
    content_root: Path,
) -> None:
    """Emit one INFO line per canonical workspace path checked at boot.

    Args:
        rel_path (str): Workspace-relative path (dir name or markdown filename).
        status (PathSeedStatus): ``created``, ``exists``, or ``skipped``.
        content_root (Path): Resolved workspace content root (for log context only).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     _log_canonical_path_status(
        ...         rel_path="logs",
        ...         status="exists",
        ...         content_root=Path(td),
        ...     )
    """
    _ = content_root
    logger.bind(path=rel_path, status=status).info(
        "workspace_layout seeded path={} status={}",
        rel_path,
        status,
    )


def _canonical_path_statuses(
    layout: WorkspaceLayout,
    *,
    missing_dirs: tuple[str, ...],
    missing_files: tuple[str, ...],
) -> list[tuple[str, PathSeedStatus]]:
    """Map canonical checklist entries to post-seed existence status.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        missing_dirs (tuple[str, ...]): Directory names still absent after seeding.
        missing_files (tuple[str, ...]): Markdown files still absent after seeding.

    Returns:
        list[tuple[str, PathSeedStatus]]: Workspace-relative path and status pairs.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> from sevn.workspace.layout_validate import _canonical_path_statuses
        >>> lay = WorkspaceLayout(Path("/tmp/sevn.json"), Path("/tmp/ws"))
        >>> rows = _canonical_path_statuses(lay, missing_dirs=("logs",), missing_files=())
        >>> rows[0][1] in ("exists", "skipped")
        True
    """
    root = layout.content_root
    rows: list[tuple[str, PathSeedStatus]] = []
    for name in CANONICAL_WORKSPACE_DIRS:
        if name in missing_dirs:
            rows.append((name, "skipped"))
        elif (root / name).is_dir():
            rows.append((name, "exists"))
        else:
            rows.append((name, "skipped"))
    for name in CANONICAL_WORKSPACE_MD_FILES:
        if name in missing_files:
            rows.append((name, "skipped"))
        elif (root / name).is_file():
            rows.append((name, "exists"))
        else:
            rows.append((name, "skipped"))
    return rows


def validate_workspace_layout(layout: WorkspaceLayout) -> WorkspaceLayoutValidationResult:
    """Check canonical folders and markdown files under ``layout.content_root``.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout from ``sevn.json``.

    Returns:
        WorkspaceLayoutValidationResult: Missing directory and file names (empty when intact).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> from sevn.workspace.layout_validate import validate_workspace_layout
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     for name in (".sevn", "logs", "memory", "sessions", "skills"):
        ...         (root / name).mkdir()
        ...     for name in ("AGENTS.md", "sevn.bot.md", "IDENTITY.md", "MEMORY.md",
        ...                  "SOUL.md", "TOOLS.md", "USER.md", "WORKSPACE.md"):
        ...         _ = (root / name).write_text("x", encoding="utf-8")
        ...     lay = WorkspaceLayout(root / "sevn.json", root)
        ...     validate_workspace_layout(lay).ok
        True
    """
    root = layout.content_root
    missing_dirs = tuple(name for name in CANONICAL_WORKSPACE_DIRS if not (root / name).is_dir())
    missing_files = tuple(
        name for name in CANONICAL_WORKSPACE_MD_FILES if not (root / name).is_file()
    )
    return WorkspaceLayoutValidationResult(
        missing_dirs=missing_dirs,
        missing_files=missing_files,
    )


async def validate_workspace_layout_at_boot(
    *,
    layout: WorkspaceLayout,
    trace: TraceSink,
) -> WorkspaceLayoutValidationResult:
    """Seed ``skills/INDEX.md`` when missing, validate layout, and emit a trace row.

    Calls :func:`sevn.data.skills_index.ensure_workspace_index` before the canonical
    checklist (idempotent; never overwrites an operator-edited workspace INDEX).
    Emits one ``workspace_layout seeded`` INFO line per canonical path after seeding.
    The ``workspace layout mismatch`` warning fires only for paths still missing
    after that post-seed pass.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.
        trace (TraceSink): Gateway trace sink (non-raising on emit failure).

    Returns:
        WorkspaceLayoutValidationResult: Filesystem validation outcome.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(validate_workspace_layout_at_boot)
        True
    """
    from sevn.data.skills_index import SkillsStarterMissingError, ensure_workspace_index

    content_root = layout.content_root
    try:
        index_target = content_root / "skills" / "INDEX.md"
        had_index = index_target.is_file()
        ensure_workspace_index(content_root)
        if index_target.is_file() and not had_index:
            _log_canonical_path_status(
                rel_path="skills/INDEX.md",
                status="created",
                content_root=content_root,
            )
        elif index_target.is_file():
            _log_canonical_path_status(
                rel_path="skills/INDEX.md",
                status="exists",
                content_root=content_root,
            )
    except SkillsStarterMissingError as exc:
        logger.bind(starter_path=str(exc.resolved_path)).error(
            "skills_starter_missing cannot seed workspace INDEX — verify wheel "
            "data_files includes sevn/data/skills/INDEX.md starter={}",
            exc.resolved_path,
        )

    from sevn.agent.identity_reply import identity_bootstrap_incomplete_fields

    try:
        from sevn.config.loader import load_workspace
        from sevn.second_brain.layout_probe import fix_second_brain_layout
        from sevn.second_brain.witchcraft_reindex import maybe_reindex_workspace_on_startup

        cfg, _loaded = load_workspace(sevn_json=layout.sevn_json_path)
        if cfg.second_brain is not None and cfg.second_brain.enabled:
            fix_second_brain_layout(config=cfg, content_root=content_root)
            maybe_reindex_workspace_on_startup(config=cfg, content_root=content_root)
    except Exception:
        logger.bind(subsystem="second_brain").warning(
            "second_brain bootstrap at boot failed (non-fatal)"
        )

    result = validate_workspace_layout(layout)
    bootstrap_incomplete = identity_bootstrap_incomplete_fields(content_root)
    for rel_path, status in _canonical_path_statuses(
        layout,
        missing_dirs=result.missing_dirs,
        missing_files=result.missing_files,
    ):
        _log_canonical_path_status(
            rel_path=rel_path,
            status=status,
            content_root=content_root,
        )

    now_ns = time_ns()
    significant_missing_dirs = tuple(
        d for d in result.missing_dirs if d not in _OPTIONAL_WORKSPACE_DIRS
    )
    layout_ok = not significant_missing_dirs and not result.missing_files
    if layout_ok and not bootstrap_incomplete:
        kind = "workspace.layout_ok"
        trace_status = "ok"
        attrs: dict[str, object] = {}
    elif layout_ok and bootstrap_incomplete:
        kind = "workspace.layout_ok"
        trace_status = "ok"
        attrs = {"bootstrap_incomplete": list(bootstrap_incomplete)}
    else:
        kind = "workspace.layout_mismatch"
        trace_status = "warn"
        attrs = {
            "missing_dirs": list(significant_missing_dirs),
            "missing_files": list(result.missing_files),
        }
        if bootstrap_incomplete:
            attrs["bootstrap_incomplete"] = list(bootstrap_incomplete)
        logger.bind(
            missing_dirs=significant_missing_dirs,
            missing_files=result.missing_files,
            bootstrap_incomplete=bootstrap_incomplete,
        ).info("workspace layout mismatch")
    if result.missing_dirs and not significant_missing_dirs:
        logger.bind(optional_dirs=list(result.missing_dirs)).info(
            "workspace layout optional dirs absent (expected at first boot)"
        )
    try:
        await trace.emit(
            TraceEvent(
                kind=kind,
                span_id=uuid.uuid4().hex,
                parent_span_id=None,
                session_id="",
                turn_id=SYSTEM_TURN_ID,
                tier=None,
                ts_start_ns=now_ns,
                ts_end_ns=now_ns,
                status=trace_status,
                attrs=attrs,
            ),
        )
    except Exception:
        logger.bind(kind=kind).exception("workspace layout trace emit failed")
    return result


__all__ = [
    "CANONICAL_WORKSPACE_DIRS",
    "CANONICAL_WORKSPACE_MD_FILES",
    "WorkspaceLayoutValidationResult",
    "validate_workspace_layout",
    "validate_workspace_layout_at_boot",
]
