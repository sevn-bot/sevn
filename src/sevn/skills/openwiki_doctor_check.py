"""OpenWiki skill doctor probes when ``skills.openwiki.enabled`` is true.

Module: sevn.skills.openwiki_doctor_check
Depends: shutil, sevn.config.workspace_config, sevn.skills.openwiki, sevn.skills.openwiki_secrets

Exports:
    OpenwikiDoctorRow — one doctor probe outcome for OpenWiki readiness.
    probe_openwiki_skill_checks — CLI and credential probes (sync entry).
    probe_openwiki_skill_checks_async — async credential resolution helper.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from sevn.code_understanding.openwiki_runner import openwiki_missing_message
from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.openwiki import openwiki_config_enabled
from sevn.skills.openwiki_secrets import (
    OPENWIKI_LLM_API_KEY_SECRET,
    openwiki_credentials_resolved,
)


@dataclass(frozen=True)
class OpenwikiDoctorRow:
    """One doctor probe outcome for OpenWiki skill readiness."""

    check_id: str
    ok: bool
    detail: str
    hint: str | None = None
    severity: str = "warn"


async def probe_openwiki_skill_checks_async(
    cfg: WorkspaceConfig | None,
    *,
    content_root: Path,
) -> list[OpenwikiDoctorRow]:
    """Return OpenWiki CLI and credential doctor rows when the skill is enabled.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        content_root (Path): Workspace content root for secrets resolution.

    Returns:
        list[OpenwikiDoctorRow]: Empty when the skill is disabled.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> rows = asyncio.run(
        ...     probe_openwiki_skill_checks_async(None, content_root=Path("."))
        ... )
        >>> rows
        []
    """
    if not openwiki_config_enabled(cfg):
        return []

    rows: list[OpenwikiDoctorRow] = []
    if shutil.which("openwiki"):
        rows.append(
            OpenwikiDoctorRow(
                check_id="openwiki_cli",
                ok=True,
                detail="openwiki CLI found on PATH",
            ),
        )
    else:
        rows.append(
            OpenwikiDoctorRow(
                check_id="openwiki_cli",
                ok=False,
                detail=openwiki_missing_message(),
                hint="sevn openwiki install (Node >= 20)",
            ),
        )

    creds_ok, cred_detail = await openwiki_credentials_resolved(cfg, content_root=content_root)
    if creds_ok:
        rows.append(
            OpenwikiDoctorRow(
                check_id="openwiki_credentials",
                ok=True,
                detail=cred_detail,
            ),
        )
    else:
        rows.append(
            OpenwikiDoctorRow(
                check_id="openwiki_credentials",
                ok=False,
                detail=cred_detail,
                hint=(
                    f"sevn secrets set {OPENWIKI_LLM_API_KEY_SECRET} "
                    "or assign an OpenWiki-compatible provider with a stored API key"
                ),
            ),
        )
    return rows


def probe_openwiki_skill_checks(
    cfg: WorkspaceConfig | None,
    *,
    content_root: Path,
) -> list[OpenwikiDoctorRow]:
    """Sync wrapper for :func:`probe_openwiki_skill_checks_async`.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.
        content_root (Path): Workspace content root.

    Returns:
        list[OpenwikiDoctorRow]: Probe rows (empty when skill disabled).

    Examples:
        >>> probe_openwiki_skill_checks(None, content_root=Path("."))
        []
    """
    import asyncio

    return asyncio.run(probe_openwiki_skill_checks_async(cfg, content_root=content_root))
