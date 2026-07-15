"""Witchcraft semantic hook (`specs/27-second-brain.md` §11).

Dispatches to the ``witchcraft`` CLI binary when available and the index is fresh
(< 5 min); falls back to lexical-only when the binary is absent, the db is missing,
or the index is stale. All callables accept an optional ``witchcraft_cfg``; when
``None`` they return stub values so callers stay keyword/``index.md`` only.

Exports:
    WitchcraftConfig — typed ``witchcraft.*`` subtree model parsed from ``sevn.json``.
    build_wiki_index — synchronous index build via ``witchcraft index`` CLI.
    index_age_seconds — seconds since the index db was last updated.
    maybe_reindex_on_startup — startup reindex when ``reindex_on_startup`` is set.
    maybe_semantic_scores — optional per-hit score boosts from the binary.
    schedule_reindex_debounced — async 60 s debounced reindex trigger.
    semantic_mode_allowed — whether semantic ranking may run (binary + fresh index).
    witchcraft_indexer_available — whether the Witchcraft binary + db are present.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess  # nosec B404
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH: str = ".sevn/witchcraft.sqlite"
_INDEX_FRESHNESS_SECONDS: int = 300  # 5 minutes


@dataclass(frozen=True)
class WitchcraftConfig:
    """Typed ``witchcraft.*`` config subtree from ``sevn.json``.

    Examples:
        >>> WitchcraftConfig().db_path
        '.sevn/witchcraft.sqlite'
        >>> WitchcraftConfig().reindex_on_startup
        False
    """

    db_path: str = DEFAULT_DB_PATH
    reindex_on_startup: bool = False
    index_messages: bool = False
    model_backend: str = "default"

    @classmethod
    def from_workspace_config(cls, workspace_config: Any) -> WitchcraftConfig | None:
        """Parse a :class:`WitchcraftConfig` from a ``WorkspaceConfig`` instance.

        Returns ``None`` when ``witchcraft_enabled`` is not truthy in the root config,
        so callers can use ``None`` as a sentinel for "Witchcraft is off."

        Args:
            workspace_config (Any): Parsed ``WorkspaceConfig`` or ``None``.

        Returns:
            WitchcraftConfig | None: Parsed config, or ``None`` when not enabled.

        Examples:
            >>> WitchcraftConfig.from_workspace_config(None) is None
            True
        """
        if workspace_config is None:
            return None
        extra = getattr(workspace_config, "model_extra", None) or {}
        if not extra.get("witchcraft_enabled"):
            return None
        wc_raw = extra.get("witchcraft", {})
        if not isinstance(wc_raw, dict):
            wc_raw = {}
        return cls(
            db_path=str(wc_raw.get("db_path", DEFAULT_DB_PATH)),
            reindex_on_startup=bool(wc_raw.get("reindex_on_startup", False)),
            index_messages=bool(wc_raw.get("index_messages", False)),
            model_backend=str(wc_raw.get("model_backend", "default")),
        )


def _witchcraft_binary() -> str | None:
    """Return path to the ``witchcraft`` binary, or ``None`` if not on PATH.

    Returns:
        str | None: Absolute path string from ``shutil.which``, or ``None``.

    Examples:
        >>> result = _witchcraft_binary()
        >>> result is None or isinstance(result, str)
        True
    """
    return shutil.which("witchcraft")


def _resolve_db(cfg: WitchcraftConfig, workspace_path: Path | None) -> Path:
    """Resolve ``cfg.db_path`` relative to ``workspace_path`` when not absolute.

    Args:
        cfg (WitchcraftConfig): Witchcraft config instance.
        workspace_path (Path | None): Workspace root for relative path resolution.

    Returns:
        Path: Resolved database path (may not exist yet).

    Examples:
        >>> from pathlib import Path
        >>> _resolve_db(WitchcraftConfig(db_path=".sevn/w.sqlite"), None)
        PosixPath('.sevn/w.sqlite')
    """
    p = Path(cfg.db_path)
    if not p.is_absolute() and workspace_path is not None:
        return workspace_path / p
    return p


def _index_mtime(db: Path) -> float | None:
    """Return mtime of ``db`` as a POSIX timestamp, or ``None`` when missing.

    Args:
        db (Path): Database file path.

    Returns:
        float | None: ``db.stat().st_mtime`` or ``None`` on ``OSError``.

    Examples:
        >>> from pathlib import Path
        >>> _index_mtime(Path("/nonexistent/w.sqlite")) is None
        True
    """
    try:
        return db.stat().st_mtime
    except OSError:
        return None


def index_age_seconds(
    witchcraft_cfg: WitchcraftConfig,
    workspace_path: Path | None = None,
) -> float | None:
    """Return seconds since the Witchcraft index db was last updated.

    Args:
        witchcraft_cfg (WitchcraftConfig): Typed config providing ``db_path``.
        workspace_path (Path | None): Workspace root for relative path resolution.

    Returns:
        float | None: Age in seconds, or ``None`` when the db file is absent.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> cfg = WitchcraftConfig(db_path="nonexistent.sqlite")
        >>> index_age_seconds(cfg, Path(tempfile.mkdtemp())) is None
        True
    """
    db = _resolve_db(witchcraft_cfg, workspace_path)
    mtime = _index_mtime(db)
    if mtime is None:
        return None
    return time.time() - mtime


def witchcraft_indexer_available(
    witchcraft_cfg: WitchcraftConfig | None = None,
    workspace_path: Path | None = None,
) -> bool:
    """Whether the Witchcraft indexer binary (and optionally db) is present.

    Registration-time readiness probe (distinct from the per-query freshness check
    :func:`semantic_mode_allowed`): when ``False``, ``semantic_search`` must not be
    registered so the model never plans around a tool that can only return
    ``DISABLED_TOOL`` (`specs/27-second-brain.md` §11; quarantine).

    Args:
        witchcraft_cfg (WitchcraftConfig | None): Optional config for db existence check.
        workspace_path (Path | None): Workspace root for relative db path resolution.

    Returns:
        bool: ``True`` when binary is on PATH **and** (when config supplied) db exists.

    Examples:
        >>> witchcraft_indexer_available()
        False
    """
    if _witchcraft_binary() is None:
        return False
    if witchcraft_cfg is None:
        return True
    db = _resolve_db(witchcraft_cfg, workspace_path)
    return db.exists()


def semantic_mode_allowed(
    witchcraft_cfg: WitchcraftConfig | None = None,
    workspace_path: Path | None = None,
) -> bool:
    """True only when a Witchcraft index is available and younger than five minutes.

    Args:
        witchcraft_cfg (WitchcraftConfig | None): Optional config for freshness probe.
        workspace_path (Path | None): Workspace root for relative db path resolution.

    Returns:
        bool: ``False`` when binary missing, db absent, or index older than 5 min.

    Examples:
        >>> semantic_mode_allowed()
        False
    """
    if _witchcraft_binary() is None:
        return False
    if witchcraft_cfg is None:
        return False
    age = index_age_seconds(witchcraft_cfg, workspace_path)
    if age is None:
        return False
    return age < _INDEX_FRESHNESS_SECONDS


def maybe_semantic_scores(
    _user_wiki: Path,
    *,
    query: str,
    _shared_wiki: Path | None,
    witchcraft_cfg: WitchcraftConfig | None = None,
    workspace_path: Path | None = None,
) -> dict[tuple[str, str], float] | None:
    """Return per-(origin, relpath) score boosts, or ``None`` to skip semantic merge.

    Dispatches ``witchcraft query --db <db> --wiki <wiki> --json <query>`` and
    parses the JSON response into a score map. Returns ``None`` on any error so
    callers stay keyword/``index.md`` only (`specs/27-second-brain.md` §6).

    Args:
        _user_wiki (Path): User wiki root passed to the binary.
        query (str): Query text forwarded to ``witchcraft query``.
        _shared_wiki (Path | None): Shared wiki root (reserved for future wiring).
        witchcraft_cfg (WitchcraftConfig | None): Optional config for binary dispatch.
        workspace_path (Path | None): Workspace root for relative db path resolution.

    Returns:
        dict[tuple[str, str], float] | None: Score boosts keyed ``(origin, relpath)``,
        or ``None`` when semantic is unavailable or the binary call fails.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> maybe_semantic_scores(Path(tempfile.mkdtemp()), query="q", _shared_wiki=None) is None
        True
    """
    if not semantic_mode_allowed(witchcraft_cfg, workspace_path):
        return None
    binary = _witchcraft_binary()
    if binary is None or witchcraft_cfg is None:
        return None
    db = _resolve_db(witchcraft_cfg, workspace_path)
    try:
        result = subprocess.run(  # nosec B603
            [binary, "query", "--db", str(db), "--wiki", str(_user_wiki), "--json", query],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        raw: list[dict[str, Any]] = json.loads(result.stdout)
        scores: dict[tuple[str, str], float] = {}
        for item in raw:
            origin = str(item.get("origin", "user"))
            path_ = str(item.get("path", ""))
            score = float(item.get("score", 0.0))
            if path_:
                scores[(origin, path_)] = score
        return scores or None
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def build_wiki_index(
    user_wiki: Path | Sequence[Path],
    *,
    witchcraft_cfg: WitchcraftConfig,
    workspace_path: Path | None = None,
    shared_wiki: Path | None = None,
) -> bool:
    """Build or refresh the Witchcraft wiki index synchronously.

    Runs ``witchcraft index --db <db> <wiki>… [--shared-wiki <shared>]``. When
    ``user_wiki`` is a sequence (PARA content roots), each root is passed to the
    binary. Creates the db parent directory when absent. Returns ``False`` when the
    binary is absent or the subprocess exits non-zero.

    Args:
        user_wiki (Path | Sequence[Path]): User wiki root(s) to index.
        witchcraft_cfg (WitchcraftConfig): Typed config providing ``db_path``.
        workspace_path (Path | None): Workspace root for relative db path resolution.
        shared_wiki (Path | None): Optional shared wiki to include in the index.

    Returns:
        bool: ``True`` when the binary exits 0; ``False`` otherwise.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> build_wiki_index(Path(tempfile.mkdtemp()), witchcraft_cfg=WitchcraftConfig())
        False
    """
    binary = _witchcraft_binary()
    if binary is None:
        return False
    db = _resolve_db(witchcraft_cfg, workspace_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    wiki_roots = user_wiki if isinstance(user_wiki, tuple) else (user_wiki,)
    cmd = [binary, "index", "--db", str(db), *[str(root) for root in wiki_roots]]
    if shared_wiki and shared_wiki.is_dir():
        cmd.extend(["--shared-wiki", str(shared_wiki)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)  # nosec B603
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return False


_REINDEX_TASK: asyncio.Task[None] | None = None


async def _run_delayed_reindex(
    user_wiki: Path | Sequence[Path],
    witchcraft_cfg: WitchcraftConfig,
    workspace_path: Path | None,
    shared_wiki: Path | None,
    delay_seconds: float,
) -> None:
    """Sleep then build the index; backing coroutine for :func:`schedule_reindex_debounced`.

    Args:
        user_wiki (Path): User wiki root.
        witchcraft_cfg (WitchcraftConfig): Typed config.
        workspace_path (Path | None): Workspace root for db path resolution.
        shared_wiki (Path | None): Optional shared wiki.
        delay_seconds (float): Seconds to sleep before indexing.

    Returns:
        None

    Examples:
        >>> _run_delayed_reindex.__name__
        '_run_delayed_reindex'
    """
    await asyncio.sleep(delay_seconds)
    build_wiki_index(
        user_wiki,
        witchcraft_cfg=witchcraft_cfg,
        workspace_path=workspace_path,
        shared_wiki=shared_wiki,
    )


async def schedule_reindex_debounced(
    user_wiki: Path | Sequence[Path],
    *,
    witchcraft_cfg: WitchcraftConfig | None,
    workspace_path: Path | None = None,
    shared_wiki: Path | None = None,
    delay_seconds: float = 60.0,
) -> None:
    """Schedule a debounced wiki reindex; cancels any pending reindex task.

    Silently does nothing when witchcraft is unconfigured or the binary is absent.
    Designed to be called from ``wiki_apply_tool`` after a successful write so the
    semantic index stays reasonably fresh without blocking the tool response.

    Args:
        user_wiki (Path): User wiki root to reindex.
        witchcraft_cfg (WitchcraftConfig | None): Config (skips when ``None``).
        workspace_path (Path | None): Workspace root for relative db resolution.
        shared_wiki (Path | None): Optional shared wiki to include.
        delay_seconds (float): Debounce delay before triggering the rebuild (default 60 s).

    Returns:
        None

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(schedule_reindex_debounced(Path('/tmp'), witchcraft_cfg=None))
    """
    global _REINDEX_TASK
    if witchcraft_cfg is None or _witchcraft_binary() is None:
        return
    if _REINDEX_TASK is not None and not _REINDEX_TASK.done():
        _REINDEX_TASK.cancel()
    _REINDEX_TASK = asyncio.create_task(
        _run_delayed_reindex(user_wiki, witchcraft_cfg, workspace_path, shared_wiki, delay_seconds)
    )


def maybe_reindex_on_startup(
    witchcraft_cfg: WitchcraftConfig | None,
    user_wiki: Path | Sequence[Path],
    *,
    workspace_path: Path | None = None,
    shared_wiki: Path | None = None,
) -> None:
    """Trigger a synchronous index build on startup when ``reindex_on_startup`` is set.

    Silently does nothing when witchcraft is unconfigured, the binary is absent, or
    ``reindex_on_startup`` is ``False``.

    Args:
        witchcraft_cfg (WitchcraftConfig | None): Typed config (skips when ``None``).
        user_wiki (Path): User wiki root to index.
        workspace_path (Path | None): Workspace root for relative db resolution.
        shared_wiki (Path | None): Optional shared wiki to include.

    Returns:
        None

    Examples:
        >>> from pathlib import Path
        >>> maybe_reindex_on_startup(None, Path('/tmp'))
    """
    if witchcraft_cfg is None or not witchcraft_cfg.reindex_on_startup:
        return
    if _witchcraft_binary() is None:
        return
    build_wiki_index(
        user_wiki,
        witchcraft_cfg=witchcraft_cfg,
        workspace_path=workspace_path,
        shared_wiki=shared_wiki,
    )


__all__ = [
    "DEFAULT_DB_PATH",
    "WitchcraftConfig",
    "build_wiki_index",
    "index_age_seconds",
    "maybe_reindex_on_startup",
    "maybe_semantic_scores",
    "schedule_reindex_debounced",
    "semantic_mode_allowed",
    "witchcraft_indexer_available",
]
