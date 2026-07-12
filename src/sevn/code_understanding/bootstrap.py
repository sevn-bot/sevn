"""Operator bootstrap for code orientation (MYCODE scan, Graphify hints).

Module: sevn.code_understanding.bootstrap
Depends: sevn.code_understanding.graphify, sevn.code_understanding.mycode_cache

Exports:
    code_orientation_doctor_checks — warnings for ``sevn doctor``.
    refresh_mycode_scan_cache — deterministic MYCODE scan when stale or missing.
    mycode_needs_refresh — True when MYCODE artefacts are missing or stale.
"""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.effective_settings import effective_graphify_settings
from sevn.code_understanding.graphify import graph_report_path, resolve_profiles
from sevn.code_understanding.mycode_cache import scan_repo_cached
from sevn.config.defaults import DEFAULT_GRAPHIFY_SEVN_OUTPUT_REL
from sevn.config.workspace_config import WorkspaceConfig  # noqa: TC001

_MYCODE_REL = Path(".index/mycode/MYCODE.md")
_MYCODE_STALE_ANCHOR = Path("pyproject.toml")


def code_orientation_doctor_checks(
    workspace: WorkspaceConfig,
    checkout: Path | None,
) -> list[str]:
    """Return human-readable warnings when code orientation assets are missing.

    Args:
        workspace (WorkspaceConfig): Parsed workspace root.
        checkout (Path | None): Resolved sevn.bot checkout.

    Returns:
        list[str]: Warning lines (empty when nothing to report).

    Examples:
        >>> warnings = code_orientation_doctor_checks(WorkspaceConfig.minimal(), None)
        >>> isinstance(warnings, list) and len(warnings) >= 1
        True
    """
    if checkout is None:
        return [
            "my_sevn.repo_path not set in sevn.json and sevn.bot checkout not found; "
            "the source_code/ mirror and Triager code orientation are disabled.",
        ]
    warnings: list[str] = []
    graphify = effective_graphify_settings(workspace, checkout)
    if graphify.enabled:
        profiles = resolve_profiles(graphify, checkout)
        if profiles and not graph_report_path(profiles[0]).is_file():
            out = profiles[0].output_dir or str(checkout / DEFAULT_GRAPHIFY_SEVN_OUTPUT_REL)
            warnings.append(
                f"Graphify enabled but GRAPH_REPORT.md missing under {out}; "
                "run graphify build or the graphify skill from repo root.",
            )
    mycode = checkout / _MYCODE_REL
    if not mycode.is_file():
        warnings.append(
            f"MYCODE.md missing at {mycode.as_posix()}; "
            "run `sevn doctor --code-orientation` or mycode-scan skill.",
        )
    return warnings


def refresh_mycode_scan_cache(
    checkout: Path,
    *,
    ignore: list[str] | None = None,
) -> Path:
    """Run a deterministic MYCODE scan and refresh the on-disk cache.

    Does not invoke the LLM ``MYCODE.md`` generator; operators use mycode-scan for that.

    Args:
        checkout (Path): sevn.bot checkout root.
        ignore (list[str] | None, optional): Extra ignore globs for the walker.

    Returns:
        Path: Path to ``.sevn/mycode-scan.cache.json`` under the checkout.

    Examples:
        >>> refresh_mycode_scan_cache.__name__
        'refresh_mycode_scan_cache'
    """
    patterns = list(ignore or [])
    scan_repo_cached(checkout, patterns)
    return checkout / ".sevn" / "mycode-scan.cache.json"


def mycode_needs_refresh(checkout: Path) -> bool:
    """Return True when MYCODE cache or markdown is missing or older than pyproject.

    Args:
        checkout (Path): sevn.bot checkout root.

    Returns:
        bool: True when a scan refresh is recommended.

    Examples:
        >>> from pathlib import Path
        >>> mycode_needs_refresh(Path("/nonexistent"))
        True
    """
    anchor = checkout / _MYCODE_STALE_ANCHOR
    mycode = checkout / _MYCODE_REL
    cache = checkout / ".sevn" / "mycode-scan.cache.json"
    if not anchor.is_file():
        return not cache.is_file()
    anchor_mtime = anchor.stat().st_mtime
    for path in (mycode, cache):
        if not path.is_file():
            return True
        if path.stat().st_mtime < anchor_mtime:
            return True
    return False


__all__ = [
    "code_orientation_doctor_checks",
    "mycode_needs_refresh",
    "refresh_mycode_scan_cache",
]
