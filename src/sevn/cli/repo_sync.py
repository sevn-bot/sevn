"""Source-checkout sync for ``sevn sync`` (operator CLI).

Module: sevn.cli.repo_sync
Depends: os, pathlib, shutil, subprocess, dataclasses

Exports:
    RepoSyncError — precondition or git failure.
    SyncResult — outcome summary for callers.
    resolve_sevn_repo_root — locate the sevn.bot git checkout.
    sync_source_tree — fetch, fast-forward or reset, run ``make sync-cli``, optional gateway restart.

Private:
    _repo_root_from_workspace — checkout recorded as ``my_sevn.repo_path`` in the bound config.
    _git — run git in ``repo_root``.
    _is_ancestor — merge-base helper.
    _run_sync_cli — invoke ``make sync-cli`` in the checkout (editable CLI + browser-cdp).
    _maybe_build_graphify — best-effort ``graphify update`` to refresh ``.index/graphify``.
    _maybe_logo_mark_animate — run ``make logo-mark-animate`` on ``--latest`` when TTY.
    _refresh_workspace_skills — replace ``skills/core`` from bundled tree when installed.
    _maybe_restart_gateway — restart gateway user unit when active.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from sevn.cli.operator_lock import OperatorLockHeld, operator_lock
from sevn.cli.service_manager import ServiceManagerError, control_unit

# v1 tracks test-pre; switch to main per specs/23-cli.md §11 when stable ships on main.
SYNC_TRACKING_BRANCH = "test-pre"
SYNC_REMOTE = "origin"


class RepoSyncError(RuntimeError):
    """Sync precondition or subprocess failure."""

    def __init__(self, message: str, *, exit_code: int = 4) -> None:
        """Attach an operator-facing message and CLI exit code.

        Args:
            message (str): Human-readable failure text.
            exit_code (int): Typer exit code (default ``4`` precondition).

        Examples:
            >>> RepoSyncError("x").exit_code
            4
        """
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class SyncResult:
    """Outcome of a source sync run."""

    updated: bool
    local_rev: str
    remote_rev: str
    detail: str


def _repo_root_from_workspace() -> Path | None:
    """Return the checkout recorded as ``my_sevn.repo_path`` in the bound ``sevn.json``.

    The gateway and its user services run from this checkout, so ``sevn sync`` should
    target it regardless of the operator's current directory — otherwise running ``sevn
    sync`` from a second clone updates that clone while the gateway keeps importing the
    old one. Reads the raw JSON (no full schema validation) so a newer/older ``sevn.json``
    still resolves, and reuses :func:`_is_sevn_repo` so a stale path is ignored.

    Returns:
        Path | None: The configured checkout, or ``None`` when no workspace is bound, the
            file is unreadable, ``my_sevn.repo_path`` is unset, or it is not a sevn checkout.

    Examples:
        >>> isinstance(_repo_root_from_workspace(), (type(None), Path))
        True
    """
    try:
        from sevn.config.loader import bound_sevn_json_path
    except ImportError:  # pragma: no cover - config package always present in practice
        return None
    bound = bound_sevn_json_path()
    try:
        data = json.loads(bound.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = ""
    if isinstance(data, dict):
        block = data.get("my_sevn")
        if isinstance(block, dict):
            raw = str(block.get("repo_path") or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    return root if _is_sevn_repo(root) else None


def resolve_sevn_repo_root(explicit: Path | None = None) -> Path:
    """Locate the sevn.bot repository checkout.

    Resolution order: explicit argument, ``SEVN_REPO_ROOT``, the bound workspace's
    ``my_sevn.repo_path`` (the checkout the gateway runs from), then walk parents from
    ``Path.cwd()`` for a ``.git`` tree whose ``pyproject.toml`` declares ``name = "sevn"``.
    Preferring the configured ``repo_path`` keeps ``sevn sync`` deterministic and pointed
    at the gateway's tree even when invoked from a different clone.

    Args:
        explicit (Path | None): Operator-provided checkout root.

    Returns:
        Path: Absolute repository root.

    Raises:
        RepoSyncError: When no checkout can be resolved.

    Examples:
        >>> from pathlib import Path
        >>> import inspect
        >>> root = Path(inspect.getfile(resolve_sevn_repo_root)).resolve().parents[3]
        >>> resolve_sevn_repo_root(root) == root
        True
    """
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not _is_sevn_repo(root):
            msg = f"not a sevn.bot git checkout: {root}"
            raise RepoSyncError(msg)
        return root
    env = os.environ.get("SEVN_REPO_ROOT", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if not _is_sevn_repo(root):
            msg = f"SEVN_REPO_ROOT is not a sevn.bot git checkout: {root}"
            raise RepoSyncError(msg)
        return root
    configured = _repo_root_from_workspace()
    if configured is not None:
        return configured
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if _is_sevn_repo(candidate):
            return candidate.resolve()
    msg = (
        "could not find sevn.bot source checkout "
        "(set SEVN_REPO_ROOT, record my_sevn.repo_path, or run from inside the repository)"
    )
    raise RepoSyncError(msg)


def _is_sevn_repo(path: Path) -> bool:
    """Return True when ``path`` looks like the sevn.bot git tree.

    Args:
        path (Path): Candidate repository root.

    Returns:
        bool: True when ``.git`` and ``pyproject.toml`` name the sevn package.

    Examples:
        >>> _is_sevn_repo(Path("/nonexistent"))
        False
    """
    if not (path / ".git").exists():
        return False
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return False
    text = pyproject.read_text(encoding="utf-8")
    return bool(re.search(r'^name\s*=\s*["\']sevn["\']', text, re.MULTILINE))


def _git(repo_root: Path, *args: str, dry_run: bool = False) -> str:
    """Run ``git`` with ``repo_root`` as cwd.

    Args:
        repo_root (Path): Repository root.
        args (str): Git subcommand argv tail (zero or more positional args).
        dry_run (bool): Print the command and return a placeholder when True.

    Returns:
        str: Stripped stdout on success.

    Raises:
        RepoSyncError: When git is missing or the command fails.

    Examples:
        >>> _git(Path("."), "rev-parse", "HEAD", dry_run=True)
        'dry-run'
    """
    if dry_run:
        return "dry-run"
    git_bin = shutil.which("git")
    if git_bin is None:
        raise RepoSyncError("git not found on PATH")
    cmd = [git_bin, *args]
    env = os.environ.copy()
    # Never block cron/doctest/CI on an interactive GitHub username prompt.
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    proc = subprocess.run(  # nosec B603
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        msg = f"{' '.join(cmd)} failed ({proc.returncode}): {detail}"
        raise RepoSyncError(msg)
    return (proc.stdout or "").strip()


def _is_ancestor(repo_root: Path, older: str, newer: str, *, dry_run: bool = False) -> bool:
    """Return True when ``older`` is an ancestor of ``newer``.

    Args:
        repo_root (Path): Repository root.
        older (str): Ancestor commit-ish.
        newer (str): Descendant commit-ish.
        dry_run (bool): Assume False when planning only.

    Returns:
        bool: True when merge-base reports ancestry.

    Examples:
        >>> _is_ancestor(Path("."), "a", "b", dry_run=True)
        False
    """
    if dry_run:
        return False
    git_bin = shutil.which("git")
    if git_bin is None:
        return False
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    proc = subprocess.run(  # nosec B603
        [git_bin, "merge-base", "--is-ancestor", older, newer],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return proc.returncode == 0


def _ensure_tracking_branch(repo_root: Path, *, dry_run: bool = False) -> None:
    """Check out the configured tracking branch, creating it from remote when needed.

    Args:
        repo_root (Path): Repository root.
        dry_run (bool): Skip mutating git commands when True.

    Examples:
        >>> _ensure_tracking_branch(Path("."), dry_run=True) is None
        True
    """
    remote_ref = f"{SYNC_REMOTE}/{SYNC_TRACKING_BRANCH}"
    listed = _git(repo_root, "branch", "--list", SYNC_TRACKING_BRANCH, dry_run=dry_run)
    if dry_run:
        return
    if SYNC_TRACKING_BRANCH in listed:
        _git(repo_root, "checkout", SYNC_TRACKING_BRANCH)
    else:
        _git(repo_root, "checkout", "-B", SYNC_TRACKING_BRANCH, remote_ref)


def _run_sync_cli(repo_root: Path, *, dry_run: bool = False) -> None:
    """Run ``make sync-cli`` in the checkout (editable CLI + browser-cdp from tree tip).

    Args:
        repo_root (Path): Repository root.
        dry_run (bool): Print the planned command only when True.

    Raises:
        RepoSyncError: When make is missing or the target fails.

    Examples:
        >>> _run_sync_cli(Path("."), dry_run=True) is None
        True
    """
    if dry_run:
        return
    make_bin = shutil.which("make")
    if make_bin is None:
        raise RepoSyncError("make not found on PATH (install make or run from a dev checkout)")
    proc = subprocess.run(  # nosec B603
        [make_bin, "sync-cli"],
        cwd=repo_root,
        check=False,
    )
    if proc.returncode != 0:
        msg = f"make sync-cli failed ({proc.returncode})"
        raise RepoSyncError(msg)


def _maybe_build_graphify(repo_root: Path, *, dry_run: bool = False) -> str | None:
    """Build/refresh the Graphify index for ``repo_root`` (best-effort, non-fatal).

    Runs ``graphify update`` (AST-only, no LLM) so ``graphify query`` and the
    ``source_code`` graph orientation have a ``graphify-out/graph.json`` +
    ``GRAPH_REPORT.md`` to read from the checkout, and links ``.index/graphify``.
    Skipped with an actionable hint when the ``graphify`` CLI is not on PATH; never
    raises, so a missing/broken CLI can never fail ``sevn sync``.

    Args:
        repo_root (Path): sevn.bot checkout root to index.
        dry_run (bool): Report intent without running when True.

    Returns:
        str | None: Summary line, or None when skipped (no CLI / dry-run no-op).

    Examples:
        >>> from pathlib import Path
        >>> _maybe_build_graphify(Path("."), dry_run=True)
        'dry-run: graphify update (build .index/graphify)'
    """
    if dry_run:
        return "dry-run: graphify update (build .index/graphify)"
    if shutil.which("graphify") is None:
        return None
    from sevn.code_understanding.graphify_seed import build_graphify_index

    return "built .index/graphify" if build_graphify_index(repo_root) else None


def _maybe_logo_mark_animate(
    repo_root: Path,
    *,
    latest: bool,
    dry_run: bool = False,
) -> str | None:
    """Run ``make logo-mark-animate`` after a ``--latest`` sync on interactive stdout.

    Args:
        repo_root (Path): Repository root for ``make``.
        latest (bool): Whether ``--latest`` was passed.
        dry_run (bool): Report intent without running make when True.

    Returns:
        str | None: Summary line, or None when skipped.

    Examples:
        >>> _maybe_logo_mark_animate(Path("."), latest=False, dry_run=True) is None
        True
        >>> _maybe_logo_mark_animate(Path("."), latest=True, dry_run=True)
        'dry-run: make logo-mark-animate'
    """
    if not latest:
        return None
    if dry_run:
        return "dry-run: make logo-mark-animate"
    from sevn.branding.splash import logo_splash_enabled

    if not logo_splash_enabled():
        return None
    make_bin = shutil.which("make")
    if make_bin is None:
        return None
    proc = subprocess.run(  # nosec B603
        [make_bin, "logo-mark-animate"],
        cwd=repo_root,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return "logo-mark-animate"


def _refresh_workspace_skills(*, dry_run: bool = False) -> str | None:
    """Replace deployed ``skills/core`` packages from the shipped bundled tree.

    Args:
        dry_run (bool): Report intent without writing when True.

    Returns:
        str | None: Human-readable summary, or None when no operator workspace exists.

    Examples:
        >>> import json, os, tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> home = Path(tempfile.mkdtemp())
        >>> _ = (home / "workspace").mkdir()
        >>> _ = (home / "workspace" / "sevn.json").write_text(
        ...     json.dumps({
        ...         "schema_version": 1,
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     }),
        ...     encoding="utf-8",
        ... )
        >>> with patch.dict(os.environ, {"SEVN_HOME": str(home)}):
        ...     _refresh_workspace_skills(dry_run=True) is not None
        True
    """
    from sevn.cli.workspace import bound_sevn_json_path

    ws_json = bound_sevn_json_path()
    if not ws_json.is_file():
        return None
    if dry_run:
        return "dry-run: refresh workspace skills/core from bundled tree"
    from sevn.onboarding.seed import refresh_bundled_core_skills

    refreshed = refresh_bundled_core_skills(ws_json.parent.resolve())
    if not refreshed:
        return None
    preview = ", ".join(refreshed[:5])
    suffix = f" (+{len(refreshed) - 5} more)" if len(refreshed) > 5 else ""
    return f"refreshed skills/core ({len(refreshed)}): {preview}{suffix}"


def _maybe_provision_host_deps(*, dry_run: bool = False) -> str | None:
    """Install operator-selected host dependencies (ripgrep/deno/pango/docker/whisper_cpp/ffmpeg).

    Reads the bound workspace ``provisioning`` config: when ``on_sync`` is true and
    ``auto_install`` is non-empty, installs the selected-and-missing host tools — the core
    registry (ripgrep/deno/pango/docker) plus the voice-only registry (whisper_cpp/ffmpeg,
    `build-plan-from-review/waves/voice-duplex-tts-menu-log-fixes-wave-plan.md` W2). When
    whisper.cpp ends up present, also opportunistically downloads the default GGML model and
    sets ``SEVN_WHISPER_CPP_MODEL``. Best-effort — a missing/invalid config or installer failure
    degrades to ``None``/a summary line and never aborts ``sevn sync``.

    Args:
        dry_run (bool): Plan installs without running them.

    Returns:
        str | None: One-line provisioning summary, or ``None`` when nothing was selected.

    Examples:
        >>> isinstance(_maybe_provision_host_deps(dry_run=True), (str, type(None)))
        True
    """
    try:
        from sevn.cli.workspace import bound_sevn_json_path
        from sevn.config.loader import load_workspace
        from sevn.provisioning import provision_host_deps, summarize_report
        from sevn.voice.host_deps import provision_voice_deps

        sevn_json = bound_sevn_json_path()
        if not sevn_json.is_file():
            return None
        cfg, _ = load_workspace(sevn_json=sevn_json)
        prov = cfg.provisioning
        if prov is None or not prov.on_sync or not prov.auto_install:
            return None
        report = provision_host_deps(prov.auto_install, dry_run=dry_run)
        voice_report = provision_voice_deps(prov.auto_install, dry_run=dry_run)
        summary = summarize_report(report)
        voice_summary = summarize_report(voice_report)
        combined = "; ".join(part for part in (summary, voice_summary) if part)
        return combined or None
    except Exception:
        logger.exception("host_deps_sync_step_failed (non-fatal)")
        return None


def _maybe_restart_gateway(*, home: Path, dry_run: bool = False) -> str | None:
    """Restart the gateway user unit when it is currently active.

    Args:
        home (Path): Operator home for advisory lock paths.
        dry_run (bool): Report intent without signals when True.

    Returns:
        str | None: Human-readable restart line, or None when skipped.

    Raises:
        RepoSyncError: When restart fails or the operator lock is held.

    Examples:
        >>> _maybe_restart_gateway(home=Path("/tmp/h"), dry_run=True) is not None
        True
    """
    try:
        status_line = control_unit(home=home, service="gateway", action="status", dry_run=dry_run)
    except ServiceManagerError:
        return None
    if dry_run:
        return "dry-run: gateway restart when active"
    if "inactive" in status_line:
        return None
    try:
        with operator_lock(home):
            return control_unit(home=home, service="gateway", action="restart")
    except OperatorLockHeld as exc:
        raise RepoSyncError(str(exc)) from exc
    except ServiceManagerError as exc:
        raise RepoSyncError(str(exc)) from exc


def sync_source_tree(
    *,
    repo_root: Path,
    latest: bool = False,
    dry_run: bool = False,
    restart_gateway: bool = True,
    home: Path | None = None,
) -> SyncResult:
    """Fetch ``origin/<tracking-branch>``, update the checkout, and reinstall the CLI.

    Default mode fast-forwards only when the remote tip is strictly ahead of ``HEAD``.
    ``--latest`` always matches the remote tip (``git reset --hard`` when needed) and
    reruns ``make sync-cli`` even when already at the tip. Ignored and untracked files
    (for example ``.env``, ``.env.proxy``) are never removed.

    Args:
        repo_root (Path): sevn.bot checkout root.
        latest (bool): Force sync and setup even when already at the remote tip.
        dry_run (bool): Plan git and make steps without mutating disk or services.
        restart_gateway (bool): Restart gateway when its user unit is active.
        home (Path | None): Operator home for service control; defaults to ``Path.home()``.

    Returns:
        SyncResult: Whether the git tip changed and revision ids.

    Raises:
        RepoSyncError: On diverged history (without ``latest``), local-ahead, or subprocess errors.

    Examples:
        >>> sync_source_tree(repo_root=Path("."), dry_run=True).updated
        False
    """
    operator_home = home if home is not None else Path.home()
    remote_ref = f"{SYNC_REMOTE}/{SYNC_TRACKING_BRANCH}"

    if dry_run:
        plan = (
            f"dry-run: git fetch {SYNC_REMOTE} {SYNC_TRACKING_BRANCH}; "
            "update checkout; make sync-cli (install-cli-browser + browser-cdp); refresh skills/core"
        )
        refresh_line = _refresh_workspace_skills(dry_run=True)
        if refresh_line:
            plan = f"{plan}; {refresh_line}"
        graphify_line = _maybe_build_graphify(repo_root, dry_run=True)
        if graphify_line:
            plan = f"{plan}; {graphify_line}"
        provision_line = _maybe_provision_host_deps(dry_run=True)
        if provision_line:
            plan = f"{plan}; {provision_line}"
        if latest:
            animate_line = _maybe_logo_mark_animate(repo_root, latest=True, dry_run=True)
            if animate_line:
                plan = f"{plan}; {animate_line}"
        if restart_gateway:
            _maybe_restart_gateway(home=operator_home, dry_run=True)
        return SyncResult(
            updated=False,
            local_rev="dry-run",
            remote_rev="dry-run",
            detail=plan,
        )

    _git(repo_root, "fetch", SYNC_REMOTE, SYNC_TRACKING_BRANCH)
    local_rev = _git(repo_root, "rev-parse", "HEAD")
    remote_rev = _git(repo_root, "rev-parse", remote_ref)

    behind = _is_ancestor(repo_root, local_rev, remote_rev) and local_rev != remote_rev
    ahead = _is_ancestor(repo_root, remote_rev, local_rev) and local_rev != remote_rev
    diverged = local_rev != remote_rev and not behind and not ahead

    if not latest and local_rev == remote_rev:
        return SyncResult(
            updated=False,
            local_rev=local_rev,
            remote_rev=remote_rev,
            detail=f"{repo_root} already up to date with origin (pass --latest to rerun setup)",
        )

    if not latest and ahead:
        msg = f"local {SYNC_TRACKING_BRANCH} is ahead of {remote_ref}; push or reset before syncing"
        raise RepoSyncError(msg)

    if not latest and diverged:
        msg = f"local history diverged from {remote_ref}; pass --latest to reset to the remote tip"
        raise RepoSyncError(msg)

    need_git_write = latest or behind
    updated = False
    if need_git_write:
        _ensure_tracking_branch(repo_root)
        if latest:
            # --latest matches the remote tip even when behind: a ff-only merge
            # aborts on locally-regenerated tracked artifacts (e.g. the code
            # index), while reset --hard leaves untracked/ignored files intact.
            _git(repo_root, "reset", "--hard", remote_ref)
            updated = local_rev != remote_rev or ahead
        elif behind:
            _git(repo_root, "merge", "--ff-only", remote_ref)
            updated = True
        new_rev = _git(repo_root, "rev-parse", "HEAD")
        updated = updated or new_rev != local_rev
        local_rev = new_rev

    _run_sync_cli(repo_root)
    animate_line = _maybe_logo_mark_animate(repo_root, latest=latest) if latest else None
    from sevn.cli.shell_history_hooks import ensure_shell_history_hook

    hook_line = ensure_shell_history_hook()
    refresh_line = _refresh_workspace_skills()
    graphify_line = _maybe_build_graphify(repo_root)
    # Provision selected host deps before restarting so a freshly-installed tool is on PATH
    # when the gateway re-execs.
    provision_line = _maybe_provision_host_deps()
    restart_line: str | None = None
    if restart_gateway:
        restart_line = _maybe_restart_gateway(home=operator_home)

    detail = f"synced {repo_root} to {remote_ref[:12]}"
    if hook_line:
        detail = f"{detail}; {hook_line}"
    if refresh_line:
        detail = f"{detail}; {refresh_line}"
    if graphify_line:
        detail = f"{detail}; {graphify_line}"
    if provision_line:
        detail = f"{detail}; {provision_line}"
    if animate_line:
        detail = f"{detail}; {animate_line}"
    if restart_line:
        detail = f"{detail}; {restart_line}"
    return SyncResult(
        updated=updated or latest,
        local_rev=local_rev,
        remote_rev=remote_rev,
        detail=detail,
    )


__all__ = [
    "SYNC_REMOTE",
    "SYNC_TRACKING_BRANCH",
    "RepoSyncError",
    "SyncResult",
    "resolve_sevn_repo_root",
    "sync_source_tree",
]
