"""Best-effort sevn.bot checkout resolution for code-understanding defaults.

Module: sevn.config.sevn_repo
Depends: os, pathlib, re

Exports:
    is_sevn_repo — detect sevn.bot git checkout layout.
    try_resolve_sevn_repo_root — locate checkout without raising (CLI / legacy env).
    resolve_sevn_checkout_for_workspace — ``sevn.json`` ``my_sevn.repo_path`` first.
    resolve_sevn_checkout_with_origin — as above, also reporting the resolution origin.
    sevn_package_glob_prefix — ``src/sevn`` vs installed layout segment for the mirror.
    sevn_gateway_read_paths — ``source_code/`` mirror paths for gateway entry modules.
    resolve_mycode_default_root — MYCODE scan root with sevn checkout preference.

Examples:
    >>> from pathlib import Path
    >>> checkout = resolve_sevn_checkout_for_workspace(content_root=Path("/nonexistent-operator-ws"))
    >>> checkout is None or checkout.is_dir()
    True
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sevn.config.workspace_config import WorkspaceConfig

# How a checkout was resolved — lets callers treat a ``$HOME`` heuristic guess
# ("scan") differently from an explicitly configured/pinned or deterministic path.
# "editable" is the checkout the running editable ``sevn`` install lives in (i.e. where
# the operator set sevn up), which is deterministic and preferred over a folder scan.
CheckoutOrigin = Literal["pinned", "editable", "walkup", "env", "scan", "installed", "none"]


_COMMON_DEV_ROOTS: tuple[str, ...] = (
    "Documents/code",
    "code",
    "src",
    "dev",
    "projects",
    "workspace",
    "repos",
)


def is_sevn_repo(path: Path) -> bool:
    """Return True when ``path`` looks like the sevn.bot git tree.

    Args:
        path (Path): Candidate repository root.

    Returns:
        bool: True when ``.git`` and ``pyproject.toml`` name the sevn package.

    Examples:
        >>> from pathlib import Path
        >>> is_sevn_repo(Path("/nonexistent"))
        False
    """
    if not (path / ".git").exists():
        return False
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return False
    text = pyproject.read_text(encoding="utf-8")
    return bool(re.search(r'^name\s*=\s*["\']sevn["\']', text, re.MULTILINE))


def _checkout_from_env(
    env: Mapping[str, str],
    *,
    keys: tuple[str, ...] = ("SEVN_REPO_ROOT", "SEVN_SOURCE_ROOT"),
) -> Path | None:
    """Return checkout from legacy env vars when they point at a sevn.bot tree.

    Args:
        env (Mapping[str, str]): Environment mapping.
        keys (tuple[str, ...], optional): Keys to try in order.

    Returns:
        Path | None: Resolved checkout or ``None``.

    Examples:
        >>> _checkout_from_env({}) is None
        True
    """
    from pathlib import Path as _Path

    for key in keys:
        raw = env.get(key, "").strip()
        if not raw:
            continue
        root = _Path(raw).expanduser().resolve()
        if is_sevn_repo(root):
            return root
    return None


def _walk_up_sevn_repo(start: Path | None) -> Path | None:
    """Walk parents from ``start`` (or cwd) for a sevn.bot root.

    Args:
        start (Path | None): First directory to test.

    Returns:
        Path | None: Checkout root when found.

    Examples:
        >>> from pathlib import Path
        >>> _walk_up_sevn_repo(Path("/nonexistent/deep/path")) is None
        True
    """
    from pathlib import Path as _Path

    if start is not None:
        root = start.expanduser().resolve()
        if is_sevn_repo(root):
            return root
    base = start if start is not None else _Path.cwd()
    for candidate in (base, *base.parents):
        if is_sevn_repo(candidate):
            return candidate.resolve()
    return None


def try_resolve_sevn_repo_root(hint: Path | None = None) -> Path | None:
    """Return the sevn.bot git checkout when resolvable (CLI / dev fallback).

    Resolution order: explicit ``hint``, ``SEVN_REPO_ROOT`` / ``SEVN_SOURCE_ROOT``,
    then walk parents from ``hint`` or cwd. Prefer
    :func:`resolve_sevn_checkout_for_workspace` when ``sevn.json`` is available.

    Args:
        hint (Path | None, optional): Starting directory for walk-up search.

    Returns:
        Path | None: Absolute checkout root, or ``None`` when not found.

    Examples:
        >>> from pathlib import Path
        >>> try_resolve_sevn_repo_root(Path("/nonexistent")) is None
        True
    """

    if hint is not None:
        root = hint.expanduser().resolve()
        if is_sevn_repo(root):
            return root
    env_hit = _checkout_from_env(os.environ)
    if env_hit is not None:
        return env_hit
    return _walk_up_sevn_repo(hint)


def resolve_sevn_checkout_for_workspace(
    workspace: WorkspaceConfig | None = None,
    *,
    content_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the sevn.bot checkout that seeds the ``source_code/`` mirror.

    Resolution order: ``my_sevn.repo_path`` in ``sevn.json``, walk-up from
    ``content_root``, legacy ``SEVN_REPO_ROOT`` / ``SEVN_SOURCE_ROOT`` env, the
    checkout the running *editable* ``sevn`` install lives in (deterministic —
    where the operator set sevn up), a heuristic scan of common dev folders
    under ``$HOME`` keyed on ``my_sevn.repo_url``, then the running
    ``site-packages/sevn`` install as a last resort (logged at WARNING so the
    operator can pin the path).

    Args:
        workspace (WorkspaceConfig | None, optional): Parsed workspace (``my_sevn.repo_path``).
        content_root (Path | None, optional): Operator workspace ``content_root`` hint.
        env (Mapping[str, str] | None, optional): Environment mapping; defaults to ``os.environ``.

    Returns:
        Path | None: Absolute checkout root, or ``None`` when not found.

    Examples:
        >>> from pathlib import Path
        >>> checkout = resolve_sevn_checkout_for_workspace(content_root=Path("/nonexistent-operator-ws"))
        >>> checkout is None or checkout.is_dir()
        True
    """
    return resolve_sevn_checkout_with_origin(workspace, content_root=content_root, env=env)[0]


def resolve_sevn_checkout_with_origin(
    workspace: WorkspaceConfig | None = None,
    *,
    content_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[Path | None, CheckoutOrigin]:
    """Like :func:`resolve_sevn_checkout_for_workspace`, but report *how* it resolved.

    The origin lets the boot path distinguish an explicitly pinned/configured
    checkout from a ``$HOME`` heuristic guess, so only the guess is auto-pinned
    into ``sevn.json`` (a guess should become an explicit, recorded choice).

    Args:
        workspace (WorkspaceConfig | None, optional): Parsed workspace (``my_sevn.repo_path``).
        content_root (Path | None, optional): Operator workspace ``content_root`` hint.
        env (Mapping[str, str] | None, optional): Environment mapping; defaults to ``os.environ``.

    Returns:
        tuple[Path | None, CheckoutOrigin]: Resolved checkout (or ``None``) and the
            origin label (``"pinned"``, ``"editable"``, ``"walkup"``, ``"env"``,
            ``"scan"``, ``"installed"``, or ``"none"``).

    Examples:
        >>> from pathlib import Path
        >>> _, origin = resolve_sevn_checkout_with_origin(content_root=Path("/nonexistent"))
        >>> origin in {"editable", "walkup", "scan", "installed", "none"}
        True
    """
    if workspace is not None:
        from sevn.config.my_sevn import resolve_my_sevn_repo_path

        configured = resolve_my_sevn_repo_path(workspace)
        if configured is not None:
            return configured, "pinned"

    walked = _walk_up_sevn_repo(content_root)
    if walked is not None:
        return walked, "walkup"

    e = os.environ if env is None else env
    env_hit = _checkout_from_env(e)
    if env_hit is not None:
        return env_hit, "env"

    editable = _editable_sevn_repo_root()
    if editable is not None:
        return editable, "editable"

    repo_url = _repo_url_for_workspace(workspace)
    scanned = _search_common_dev_locations(repo_url, env=e)
    if scanned is not None:
        return scanned, "scan"

    installed = _installed_sevn_package_root()
    if installed is not None:
        logger.warning(
            "repo_path unresolved; falling back to installed sevn package at {} — "
            "set my_sevn.repo_path in sevn.json to silence this and mirror the full checkout",
            installed,
        )
        return installed, "installed"
    return None, "none"


def _repo_url_for_workspace(workspace: WorkspaceConfig | None) -> str | None:
    """Return ``my_sevn.repo_url`` for the workspace when present.

    Args:
        workspace (WorkspaceConfig | None): Parsed workspace.

    Returns:
        str | None: Configured GitHub-style URL or ``None``.

    Examples:
        >>> _repo_url_for_workspace(None) is None
        True
    """
    if workspace is None or workspace.my_sevn is None:
        return None
    url = (workspace.my_sevn.repo_url or "").strip()
    return url or None


def _basename_from_repo_url(repo_url: str | None) -> str | None:
    """Return the last path segment of a git URL (``foo.bar`` → ``foo.bar``).

    Args:
        repo_url (str | None): ``https://github.com/<org>/<repo>(.git)?`` style URL.

    Returns:
        str | None: Repo basename, ``.git`` suffix stripped. ``None`` when unparseable.

    Examples:
        >>> _basename_from_repo_url("https://github.com/sevn-bot/sevn.git")
        'sevn'
        >>> _basename_from_repo_url(None) is None
        True
    """
    if not repo_url:
        return None
    tail = repo_url.rstrip("/").rsplit("/", 1)[-1].strip()
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or None


def _search_common_dev_locations(
    repo_url: str | None,
    *,
    env: Mapping[str, str],
) -> Path | None:
    """Scan a small allow-list of dev folders under ``$HOME`` for a sevn.bot checkout.

    The scan prefers directories whose basename matches the repo URL tail
    (e.g. ``sevn.bot``) and validates each candidate with :func:`is_sevn_repo`.
    Two levels deep at most (e.g. ``~/Documents/code/sevn.bot/sevn.bot``).

    Args:
        repo_url (str | None): Configured ``my_sevn.repo_url`` for basename hint.
        env (Mapping[str, str]): Environment mapping (used for ``HOME``).

    Returns:
        Path | None: First valid checkout, or ``None``.

    Examples:
        >>> _search_common_dev_locations(None, env={}) is None
        True
    """
    from pathlib import Path as _Path

    home_raw = (env.get("HOME") or "").strip()
    if not home_raw:
        return None
    home = _Path(home_raw).expanduser()
    if not home.is_dir():
        return None
    preferred = _basename_from_repo_url(repo_url)

    def _candidates(base: Path) -> list[Path]:
        out: list[Path] = []
        if preferred:
            out.append(base / preferred)
            out.append(base / preferred / preferred)
        try:
            entries = sorted(p for p in base.iterdir() if p.is_dir())
        except OSError:
            entries = []
        out.extend(entries)
        return out

    for rel in _COMMON_DEV_ROOTS:
        base = home / rel
        if not base.is_dir():
            continue
        for candidate in _candidates(base):
            if not candidate.is_dir():
                continue
            if is_sevn_repo(candidate):
                return candidate.resolve()
            for nested in _candidates(candidate)[:8]:
                if nested.is_dir() and is_sevn_repo(nested):
                    return nested.resolve()
    return None


def _editable_sevn_repo_root() -> Path | None:
    """Return the git checkout that the running editable ``sevn`` install lives in.

    For ``uv tool install --editable .`` or ``uv sync`` the imported ``sevn`` package sits
    inside its source tree, so walking up from ``sevn.__file__`` reaches the checkout the
    operator set sevn up from. This is a deterministic answer to "where was sevn installed",
    so it is preferred over a ``$HOME`` folder scan that can match an unrelated clone. Returns
    ``None`` for a non-editable (wheel) install, where the package has no enclosing checkout.

    During pytest, skip editable resolution when ``HOME`` is unset or points at a per-test
    temporary directory so isolation tests for scan/env/walkup are not shadowed by the
    developer's editable checkout.

    Returns:
        Path | None: The sevn.bot checkout root, or ``None`` when not editable-installed.

    Examples:
        >>> from pathlib import Path
        >>> root = _editable_sevn_repo_root()
        >>> root is None or is_sevn_repo(root)
        True
    """
    from pathlib import Path as _Path

    if os.environ.get("PYTEST_CURRENT_TEST"):
        home = (os.environ.get("HOME") or "").strip()
        if not home or "pytest-of-" in home.replace("\\", "/"):
            return None

    try:
        import sevn as pkg
    except ImportError:  # pragma: no cover - sevn is importable in-process
        return None
    pkg_file = getattr(pkg, "__file__", None)
    if not pkg_file:
        return None
    for parent in _Path(pkg_file).resolve().parents:
        if is_sevn_repo(parent):
            return parent
    return None


def _installed_sevn_package_root() -> Path | None:
    """Return the running ``sevn`` package directory when the gateway is uv-installed.

    Used when ``my_sevn.repo_path`` is unset so the ``source_code/`` mirror still
    has source to copy from site-packages (layout without ``src/sevn/``).

    Returns:
        Path | None: Package root containing ``gateway/``, or ``None``.

    Examples:
        >>> root = _installed_sevn_package_root()
        >>> root is None or (root / "gateway").is_dir()
        True
    """
    from pathlib import Path as _Path

    try:
        import sevn as pkg
    except ImportError:
        return None
    root = _Path(pkg.__file__).resolve().parent
    if (root / "gateway").is_dir():
        return root
    return None


def sevn_package_glob_prefix(repo_root: "Path") -> str:  # noqa: UP037
    """Return the path segment to the sevn package under a mirrored ``repo_root``.

    Args:
        repo_root (Path): Resolved read root (git checkout or installed package).

    Returns:
        str: ``src/sevn`` for a git tree, or ``sevn`` for an installed package root.

    Examples:
        >>> from pathlib import Path
        >>> sevn_package_glob_prefix(Path("/nonexistent"))
        'src/sevn'
    """
    if (repo_root / "src" / "sevn").is_dir():
        return "src/sevn"
    if (repo_root / "gateway").is_dir():
        return "sevn"
    return "src/sevn"


def sevn_gateway_read_paths(repo_root: Path) -> tuple[str, str, str]:
    """Return ``source_code/`` mirror paths for core gateway modules.

    Args:
        repo_root (Path): Resolved read root used to detect the package layout.

    Returns:
        tuple[str, str, str]: ``agent_turn``, ``channel_router``, ``menu`` mirror paths.

    Examples:
        >>> from pathlib import Path
        >>> paths = sevn_gateway_read_paths(Path("/nonexistent"))
        >>> all(p.startswith("source_code/") for p in paths)
        True
    """
    prefix = sevn_package_glob_prefix(repo_root)
    base = f"source_code/{prefix}/gateway".replace("//", "/")
    return (
        f"{base}/agent_turn.py",
        f"{base}/channel_router.py",
        f"{base}/menu.py",
    )


def resolve_mycode_default_root(
    primary_repo_root: Path,
    *,
    workspace: WorkspaceConfig | None = None,
) -> Path:
    """Return the preferred MYCODE scan root for a workspace.

    Uses :func:`resolve_sevn_checkout_for_workspace` when ``workspace`` is supplied;
    otherwise falls back to :func:`try_resolve_sevn_repo_root`.

    Args:
        primary_repo_root (Path): Workspace primary repo root.
        workspace (WorkspaceConfig | None, optional): Parsed workspace for config path.

    Returns:
        Path: Absolute directory to scan for MYCODE.

    Examples:
        >>> from pathlib import Path
        >>> resolve_mycode_default_root(Path("/tmp/w")).as_posix().endswith("/tmp/w")
        True
    """
    if workspace is not None:
        sevn_root = resolve_sevn_checkout_for_workspace(
            workspace,
            content_root=primary_repo_root,
        )
        if sevn_root is not None:
            return sevn_root
    sevn_root = try_resolve_sevn_repo_root(primary_repo_root)
    if sevn_root is not None:
        return sevn_root
    return primary_repo_root.expanduser().resolve()
