"""Special-case install hooks reused from existing onboarding helpers (W6).

Module: sevn.onboarding.install_actions.special
Depends: sevn.skills.computer_use, sevn.skills.cua_agent, sevn.skills.lume, sevn.skills.openwiki_install

Exports:
    run_computer_use_validate — macOS / ``cua-driver`` or ``cua`` CLI host gate.
    run_cua_agent_validate — macOS / ``computer-use`` / ``cua`` gate for cua-agent.
    run_lume_validate — macOS Apple Silicon / ``lume`` gate.
    run_openwiki_validate — OpenWiki CLI + credential readiness when skill is opted in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sevn.cli.asyncio_util import run_sync_coro
from sevn.code_understanding.openwiki_runner import openwiki_missing_message
from sevn.skills.computer_use import validate_computer_use_host
from sevn.skills.cua_agent import validate_cua_agent_host
from sevn.skills.errors import SkillExecutionError
from sevn.skills.lume import validate_lume_host


def run_computer_use_validate(
    *,
    merged_config: dict[str, Any] | None,
    content_root: Path | None = None,
) -> tuple[int, str]:
    """Run ``validate_computer_use_host`` when computer-use is opted in.

    Validates host MCP (``cua-driver``) or sandbox CLI (``cua``) per active target.

    Args:
        merged_config (dict[str, Any] | None): Promoted workspace document.
        content_root (Path | None): Workspace content root (unused; signature parity).

    Returns:
        tuple[int, str]: ``(exit_code, detail)``.

    Examples:
        >>> code, _ = run_computer_use_validate(merged_config=None)
        >>> code in (0, 1)
        True
    """
    from sevn.config.workspace_config import parse_workspace_config

    _ = content_root
    cfg = parse_workspace_config(merged_config) if merged_config else None
    try:
        validate_computer_use_host(cfg=cfg)
    except SkillExecutionError as exc:
        return 1, str(exc)
    return 0, "computer-use host preconditions satisfied"


def run_cua_agent_validate(
    *,
    merged_config: dict[str, Any] | None,
    content_root: Path | None = None,
) -> tuple[int, str]:
    """Run ``validate_cua_agent_host`` when cua-agent is opted in.

    Args:
        merged_config (dict[str, Any] | None): Promoted workspace document.
        content_root (Path | None): Workspace content root (unused; signature parity).

    Returns:
        tuple[int, str]: ``(exit_code, detail)``.

    Examples:
        >>> code, _ = run_cua_agent_validate(merged_config=None)
        >>> code in (0, 1)
        True
    """
    from sevn.config.workspace_config import parse_workspace_config

    _ = content_root
    cfg = parse_workspace_config(merged_config) if merged_config else None
    try:
        validate_cua_agent_host(cfg=cfg)
    except SkillExecutionError as exc:
        return 1, str(exc)
    return 0, "cua-agent host preconditions satisfied"


def run_lume_validate(
    *,
    merged_config: dict[str, Any] | None,
    content_root: Path | None = None,
) -> tuple[int, str]:
    """Run ``validate_lume_host`` when lume is opted in.

    Args:
        merged_config (dict[str, Any] | None): Promoted workspace document.
        content_root (Path | None): Workspace content root (unused; signature parity).

    Returns:
        tuple[int, str]: ``(exit_code, detail)``.

    Examples:
        >>> code, _ = run_lume_validate(merged_config=None)
        >>> code in (0, 1)
        True
    """
    from sevn.config.workspace_config import parse_workspace_config

    _ = content_root
    cfg = parse_workspace_config(merged_config) if merged_config else None
    try:
        validate_lume_host(cfg=cfg)
    except SkillExecutionError as exc:
        return 1, str(exc)
    return 0, "lume host preconditions satisfied"


def run_openwiki_validate(
    *,
    merged_config: dict[str, Any] | None,
    content_root: Path | None = None,
) -> tuple[int, str]:
    """Validate OpenWiki CLI and resolvable LLM credentials when opted in.

    Args:
        merged_config (dict[str, Any] | None): Promoted or draft workspace document.
        content_root (Path | None): Workspace content root for secrets resolution.

    Returns:
        tuple[int, str]: ``(exit_code, detail)``.

    Examples:
        >>> code, _ = run_openwiki_validate(merged_config=None)
        >>> code in (0, 1)
        True
    """
    from sevn.config.workspace_config import parse_workspace_config
    from sevn.skills.openwiki import openwiki_config_enabled
    from sevn.skills.openwiki_install import openwiki_cli_installed
    from sevn.skills.openwiki_secrets import openwiki_credentials_resolved

    cfg = parse_workspace_config(merged_config) if merged_config else None
    if not openwiki_config_enabled(cfg):
        return 0, "openwiki skill not enabled — skipped"
    if not openwiki_cli_installed():
        return 1, openwiki_missing_message() + " Run: sevn openwiki install"
    root = content_root
    if root is None and merged_config is not None and cfg is not None:
        from sevn.workspace.layout import WorkspaceLayout

        ws = str(merged_config.get("workspace_root", ".")).strip() or "."
        sevn_json = Path(ws).expanduser() / "sevn.json"
        if sevn_json.is_file():
            root = WorkspaceLayout.from_config(sevn_json, cfg).content_root
    creds_ok, cred_detail = run_sync_coro(
        openwiki_credentials_resolved(cfg, content_root=root or Path("."))
    )
    if not creds_ok:
        return 1, cred_detail
    return 0, "openwiki CLI and credentials ready"


__all__ = [
    "run_computer_use_validate",
    "run_cua_agent_validate",
    "run_lume_validate",
    "run_openwiki_validate",
]
