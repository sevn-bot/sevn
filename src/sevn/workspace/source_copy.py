"""Mirror the full sevn.bot checkout into ``workspace/source_code/`` at boot.

The agent reads sevn.bot source through ordinary workspace-relative paths by
exposing a read-only mirror of the whole checkout at ``workspace/source_code/``
(e.g. ``source_code/src/sevn/gateway/agent_turn.py``,
``source_code/about-sevn.bot/...``). This gives the agent a predictable,
in-workspace tree it can reference in conversation without any special prefix and
without modifying the live install.

The mirror is read-only from the agent's point of view (the gateway never writes
through ``workspace/source_code/`` outside this refresh); it is overwritten on
every gateway boot by ``sync_source_copy``. Only git-tracked files are mirrored, so
``.gitignore`` is honoured — reference checkouts, ``plan``/``specs``/``prd``, local
notes, and caches never reach the workspace (non-git sources fall back to a filtered
filesystem walk).

Module: sevn.workspace.source_copy
Depends: shutil, pathlib

Exports:
    sync_source_copy — refresh ``workspace/source_code`` from the whole ``repo_root``.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path
from typing import Final

from loguru import logger

# Safety ceilings: a boot-time mirror must never be able to fill the disk. If a
# misresolved ``repo_root`` (or an un-excluded heavy tree) pushes the copy past
# either bound, the sync logs a warning and stops rather than running away.
_MAX_MIRROR_FILES: Final[int] = 50_000
_MAX_MIRROR_BYTES: Final[int] = 2 * 1024**3  # 2 GiB

_SKIP_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".git",
        ".worktrees",
        ".venv",
        "venv",
        "node_modules",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".tox",
        ".nox",
        ".eggs",
        "htmlcov",
        ".cache",
        ".sevn",
        ".index",
        "graphify-out",
        "reports",
        "specs",
        "prd",
        "source_code",
    },
)
_SKIP_SUFFIXES: Final[tuple[str, ...]] = (".pyc", ".pyo")


def _should_skip(path: Path) -> bool:
    """Return True when ``path`` should not be copied into the workspace mirror.

    Args:
        path (Path): Candidate file or directory under the source tree.

    Returns:
        bool: True for caches, ``.egg-info``, git/venv/build dirs, ``specs``/``prd``,
            the mirror itself, and compiled Python artifacts.

    Examples:
        >>> from pathlib import Path
        >>> _should_skip(Path("/tmp/.git"))
        True
        >>> _should_skip(Path("/tmp/specs"))
        True
        >>> _should_skip(Path("/tmp/foo/bar.pyc"))
        True
        >>> _should_skip(Path("/tmp/foo/bar.py"))
        False
    """
    if path.name in _SKIP_DIR_NAMES:
        return True
    if path.name.endswith(".egg-info"):
        return True
    return path.suffix in _SKIP_SUFFIXES


def _git_tracked_rel_paths(src_root: Path) -> list[Path] | None:
    """Return repo-relative tracked file paths via ``git ls-files`` (gitignore-aware).

    Mirroring only tracked files guarantees ``.gitignore`` is honoured, so reference
    checkouts, local notes, build output, and caches that merely sit in the checkout
    directory are never copied into the agent's workspace. Returns ``None`` when
    ``src_root`` is not a usable git checkout, so the caller falls back to a filtered
    filesystem walk (e.g. for an installed ``site-packages/sevn`` layout).

    Args:
        src_root (Path): Resolved checkout root.

    Returns:
        list[Path] | None: Tracked relative paths, or ``None`` when git is unavailable.

    Examples:
        >>> from pathlib import Path
        >>> _git_tracked_rel_paths(Path("/nonexistent")) is None
        True
    """
    import subprocess  # nosec B404 — fixed git argv only; no shell

    if not (src_root / ".git").exists():
        return None
    try:
        proc = subprocess.run(  # nosec
            ["git", "-C", str(src_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [Path(p.decode("utf-8")) for p in proc.stdout.split(b"\x00") if p]


def sync_source_copy(workspace: Path, repo_root: Path) -> int:
    """Mirror the whole ``repo_root`` into ``workspace/source_code`` (rsync-style).

    Only git-tracked files are mirrored (via ``git ls-files``), so ``.gitignore`` is
    honoured and no gitignored tree — reference checkouts, ``plan``/``specs``/``prd``,
    local notes, caches — ever reaches the workspace. Non-git sources (an installed
    package) fall back to a filtered filesystem walk (see ``_SKIP_DIR_NAMES``).

    The copy is incremental: only files whose source mtime is newer than the
    destination (or whose destination is missing) are rewritten. Files that exist
    in the destination but not in the source are pruned, so deleted modules (and
    anything no longer tracked) disappear from the mirror on the next sync.

    Args:
        workspace (Path): Workspace content root.
        repo_root (Path): Local sevn.bot checkout to mirror in full.

    Returns:
        int: Count of files written or refreshed (skipped files don't count).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(sync_source_copy)
        True
    """
    src_root = repo_root.expanduser().resolve()
    if not src_root.is_dir():
        return 0
    dst_root = (workspace / "source_code").resolve()
    dst_root.mkdir(parents=True, exist_ok=True)

    # Hard recursion guard: if the mirror lives inside the source tree, never
    # descend into it — even if it is not named ``source_code`` for some reason.
    # This is a path-containment check, independent of the fragile name-based skip.
    def _is_mirror(path: Path) -> bool:
        return path == dst_root or dst_root in path.parents

    # Prefer git: mirror only tracked files so .gitignore is honoured and no
    # gitignored tree (reference checkouts, plan/specs/prd, local notes, caches)
    # ever reaches the workspace. Fall back to a filtered filesystem walk for
    # non-git sources (e.g. an installed sevn package).
    tracked = _git_tracked_rel_paths(src_root)
    candidates = (src_root / rel for rel in tracked) if tracked is not None else src_root.rglob("*")

    src_files: set[Path] = set()
    written = 0
    copied_files = 0
    copied_bytes = 0
    capped = False
    for src_path in candidates:
        if _is_mirror(src_path):
            continue
        try:
            rel = src_path.relative_to(src_root)
        except ValueError:
            continue
        # Skip if any ancestor (or this entry) matches a skip directory/suffix.
        if any(_should_skip(Path(part)) for part in rel.parts):
            continue
        if _should_skip(src_path):
            continue
        dst_path = dst_root / rel
        if src_path.is_dir():
            dst_path.mkdir(parents=True, exist_ok=True)
            continue
        if not src_path.is_file():
            continue
        src_files.add(rel)
        try:
            stat = src_path.stat()
        except OSError:
            continue
        # Enforce the safety ceiling on the total payload we would mirror. Once
        # exceeded we stop copying (and prune only what we actually tracked), so a
        # runaway ``repo_root`` can never exhaust the disk on a boot refresh.
        copied_files += 1
        copied_bytes += stat.st_size
        if copied_files > _MAX_MIRROR_FILES or copied_bytes > _MAX_MIRROR_BYTES:
            capped = True
            break
        if dst_path.exists():
            try:
                if dst_path.stat().st_mtime >= stat.st_mtime:
                    continue
            except OSError:
                pass
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src_path, dst_path)
            written += 1
        except OSError:
            continue

    if capped:
        logger.warning(
            "source_code mirror aborted: {} exceeded the safety ceiling "
            "({} files / {} bytes seen, caps {} files / {} bytes); "
            "skipping mirror refresh to protect the disk",
            src_root,
            copied_files,
            copied_bytes,
            _MAX_MIRROR_FILES,
            _MAX_MIRROR_BYTES,
        )
        return written

    # Prune files that no longer exist in the source.
    for dst_path in dst_root.rglob("*"):
        if not dst_path.is_file():
            continue
        rel = dst_path.relative_to(dst_root)
        if rel not in src_files:
            with contextlib.suppress(OSError):
                dst_path.unlink()

    return written


__all__ = ["sync_source_copy"]
