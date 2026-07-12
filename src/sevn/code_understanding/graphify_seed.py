"""Deterministic Graphify index seeding for the ``source_code/`` mirror.

The tier-B agent is told (in ``AGENTS-detail.md``/``sevn.bot.md``) to read
``source_code/.index/graphify/GRAPH_REPORT.md`` for architecture orientation.
That file only exists if something builds the Graphify graph, so a fresh gateway
boot leaves the agent issuing repeated ``read`` "not found" errors on a path that
is never populated.

This module builds the graph directly inside the workspace ``source_code/``
mirror (where the agent's ``read`` actually resolves — the mirror is a physical
copy, not a redirect to the checkout) by shelling out to the standalone
``graphify`` CLI (``graphify update <mirror>``). ``graphify`` is not importable in
the gateway venv, so everything is a ``subprocess`` call guarded by
``shutil.which`` and degrades to a single actionable log line when the CLI is
absent. The build is AST-only (no LLM) and fast, mirroring ``_boot_seed_mycode``.

The ``sync_source_copy`` mirror skips ``.index``/``graphify-out`` and prunes any
mirror file that is not a tracked source file, so the seeded graph is rebuilt on
each boot after the mirror refresh — the staleness gate keeps that cheap by only
rebuilding when the report is missing or older than the newest ``.py`` source.

Module: sevn.code_understanding.graphify_seed
Depends: shutil, subprocess, pathlib, loguru

Exports:
    graphify_report_mirror_path — ``<mirror>/source_code/.index/graphify/GRAPH_REPORT.md``.
    graphify_needs_refresh — True when the mirror report is missing or stale.
    seed_graphify_mirror — build the Graphify graph into the source_code mirror.
    build_graphify_index — best-effort ``graphify update`` for an arbitrary checkout.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — fixed graphify argv only; no shell
from pathlib import Path

from loguru import logger

_SOURCE_CODE_REL = Path("source_code")
_GRAPHIFY_OUT_DIRNAME = "graphify-out"
_INDEX_GRAPHIFY_REL = Path(".index/graphify")
_GRAPH_REPORT_NAME = "GRAPH_REPORT.md"

# Boot seeding must never hang the lifespan; graphify update on the full mirror is
# AST-only but can still take a while on a cold cache, so cap it generously.
_GRAPHIFY_TIMEOUT_S = 600

_MISSING_CLI_HINT = (
    "graphify CLI not on PATH; source_code/.index/graphify/GRAPH_REPORT.md will be "
    "absent and the agent cannot use graph orientation. Install it with "
    "`uv sync --extra graphify` (or install the graphify package) to enable seeding."
)


def graphify_report_mirror_path(mirror_root: Path) -> Path:
    """Return the agent-visible ``GRAPH_REPORT.md`` path inside the mirror.

    This is the exact path the tier-B prompt tells the agent to read
    (``source_code/.index/graphify/GRAPH_REPORT.md``), resolved under the
    workspace content root.

    Args:
        mirror_root (Path): Workspace content root that holds ``source_code/``.

    Returns:
        Path: ``<mirror_root>/source_code/.index/graphify/GRAPH_REPORT.md``.

    Examples:
        >>> from pathlib import Path
        >>> graphify_report_mirror_path(Path("/ws")).as_posix()
        '/ws/source_code/.index/graphify/GRAPH_REPORT.md'
    """
    return mirror_root / _SOURCE_CODE_REL / _INDEX_GRAPHIFY_REL / _GRAPH_REPORT_NAME


def _newest_py_mtime(root: Path) -> float | None:
    """Return the newest ``.py`` modification time under ``root`` (or ``None``).

    Args:
        root (Path): Directory to scan recursively for Python sources.

    Returns:
        float | None: Highest ``st_mtime`` seen, or ``None`` when no ``.py`` exists.

    Examples:
        >>> from pathlib import Path
        >>> _newest_py_mtime(Path("/nonexistent")) is None
        True
    """
    newest: float | None = None
    for path in root.rglob("*.py"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def graphify_needs_refresh(mirror_root: Path) -> bool:
    """Return True when the mirror Graphify report is missing or stale.

    Stale means the ``GRAPH_REPORT.md`` under the ``source_code/`` mirror is older
    than the newest ``.py`` file in that mirror (i.e. source changed since the last
    build). A missing report always needs a refresh; a mirror with no Python at all
    (nothing to graph) does not.

    Args:
        mirror_root (Path): Workspace content root that holds ``source_code/``.

    Returns:
        bool: True when a rebuild is recommended.

    Examples:
        >>> from pathlib import Path
        >>> graphify_needs_refresh(Path("/nonexistent"))
        True
    """
    report = graphify_report_mirror_path(mirror_root)
    if not report.is_file():
        return True
    source_root = mirror_root / _SOURCE_CODE_REL
    newest_py = _newest_py_mtime(source_root)
    if newest_py is None:
        return False
    try:
        report_mtime = report.stat().st_mtime
    except OSError:
        return True
    return report_mtime < newest_py


def _ensure_index_symlink(source_root: Path) -> None:
    """Point ``source_code/.index/graphify`` at the ``graphify-out`` output dir.

    ``graphify update`` writes ``<source_root>/graphify-out/``; the agent (and
    sevn profile) expect ``.index/graphify/``. A relative symlink keeps the two in
    sync without copying. Falls back to a real directory copy of ``GRAPH_REPORT.md``
    only implicitly — callers rely on the symlink existing.

    Args:
        source_root (Path): The mirror ``source_code/`` directory.

    Returns:
        None

    Examples:
        >>> _ensure_index_symlink.__name__
        '_ensure_index_symlink'
    """
    link = source_root / _INDEX_GRAPHIFY_REL
    link.parent.mkdir(parents=True, exist_ok=True)
    target = Path("..") / _GRAPHIFY_OUT_DIRNAME
    if link.is_symlink():
        if link.readlink() == target:
            return
        link.unlink()
    elif link.exists():
        # A stale real directory (e.g. left by a previous copy) — replace it.
        shutil.rmtree(link, ignore_errors=True)
    link.symlink_to(target, target_is_directory=True)


def _run_graphify_update(target: Path) -> bool:
    """Run ``graphify update <target>`` as a subprocess (AST-only, no LLM).

    Args:
        target (Path): Directory whose Python sources should be re-extracted.

    Returns:
        bool: True when the CLI ran and exited 0, else False.

    Examples:
        >>> _run_graphify_update.__name__
        '_run_graphify_update'
    """
    graphify_bin = shutil.which("graphify")
    if graphify_bin is None:
        logger.info("graphify_seed: {}", _MISSING_CLI_HINT)
        return False
    try:
        proc = subprocess.run(  # nosec B603 — fixed argv, no shell
            [graphify_bin, "update", str(target)],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=_GRAPHIFY_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("graphify_seed: graphify update failed to launch: {}", exc)
        return False
    if proc.returncode != 0:
        logger.warning(
            "graphify_seed: graphify update exited {} ({})",
            proc.returncode,
            (proc.stderr or proc.stdout or "").strip()[:200],
        )
        return False
    return True


def seed_graphify_mirror(mirror_root: Path) -> bool:
    """Build the Graphify graph into the ``source_code/`` mirror when stale.

    Runs ``graphify update`` on ``<mirror_root>/source_code`` so the output lands at
    ``source_code/graphify-out/`` and links ``source_code/.index/graphify`` to it —
    exactly where the agent's ``read source_code/.index/graphify/GRAPH_REPORT.md``
    resolves. No-ops when the report is already current, when the mirror is absent,
    or (with a single INFO hint) when the ``graphify`` CLI is not installed.

    Args:
        mirror_root (Path): Workspace content root that holds ``source_code/``.

    Returns:
        bool: True when the graph was (re)built, False when skipped or unavailable.

    Examples:
        >>> from pathlib import Path
        >>> seed_graphify_mirror(Path("/nonexistent"))
        False
    """
    source_root = mirror_root / _SOURCE_CODE_REL
    if not source_root.is_dir():
        logger.debug("graphify_seed: no source_code mirror at {}; skipping", source_root)
        return False
    if not graphify_needs_refresh(mirror_root):
        logger.debug("graphify_seed: GRAPH_REPORT.md is current; skipping boot seed")
        return False
    if shutil.which("graphify") is None:
        logger.info("graphify_seed: {}", _MISSING_CLI_HINT)
        return False
    logger.info("graphify_seed: seeding Graphify index into {} (background)", source_root)
    if not _run_graphify_update(source_root):
        return False
    try:
        _ensure_index_symlink(source_root)
    except OSError as exc:
        logger.warning("graphify_seed: could not link .index/graphify: {}", exc)
        return False
    logger.info(
        "graphify_seed: Graphify index seeded at {}",
        graphify_report_mirror_path(mirror_root),
    )
    return True


def build_graphify_index(checkout: Path) -> bool:
    """Best-effort ``graphify update`` + ``.index/graphify`` link for a checkout.

    Used by ``sevn sync`` to refresh ``<checkout>/graphify-out`` and link
    ``<checkout>/.index/graphify`` so ``graphify query`` works from the repo root
    (per the repo ``CLAUDE.md``). Non-fatal: returns False (with a log hint) when
    the CLI is missing or the build fails.

    Args:
        checkout (Path): sevn.bot checkout root to index.

    Returns:
        bool: True when the graph was built, False when skipped or unavailable.

    Examples:
        >>> from pathlib import Path
        >>> build_graphify_index(Path("/nonexistent"))
        False
    """
    if not checkout.is_dir():
        return False
    if shutil.which("graphify") is None:
        logger.info("sync: {}", _MISSING_CLI_HINT)
        return False
    if not _run_graphify_update(checkout):
        return False
    try:
        _ensure_index_symlink(checkout)
    except OSError as exc:
        logger.warning("sync: could not link .index/graphify: {}", exc)
        return False
    logger.info("sync: Graphify index built at {}/graphify-out", checkout)
    return True


__all__ = [
    "build_graphify_index",
    "graphify_needs_refresh",
    "graphify_report_mirror_path",
    "seed_graphify_mirror",
]
