"""Skill dependency setup orchestration (issues #69 / #93, ``specs/12-skills-system.md``).

Module: sevn.skills.setup
Depends: asyncio, pathlib, shutil, sevn.onboarding.install_orchestrator

Exports:
    InstallConfirmationRequired — raised when install runs without operator confirm.
    skill_setup_status — coarse setup state for one manifest.
    skill_setup_requirements — structured unmet rows for CLI/Telegram.
    skill_setup_telegram_summary — shared setup summary for Telegram form (W14).
    execute_skill_setup — install/repair one skill's declared dependencies.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

from sevn.onboarding.capabilities_manifest import CapabilityManifest, load_manifest
from sevn.onboarding.install_orchestrator import (
    build_install_plan_for_capability_ids,
    collect_install_run,
    resolve_install_root,
)
from sevn.onboarding.uv_extra_probes import UV_EXTRA_IMPORT_PROBE
from sevn.skills.errors import SkillExecutionError
from sevn.skills.manifest import SkillManifest


class InstallConfirmationRequired(Exception):
    """Raised when a setup install is attempted without operator confirmation."""


def skill_setup_status(manifest: SkillManifest) -> str:
    """Return coarse setup state for one manifest.

    Args:
        manifest (SkillManifest): Parsed ``SKILL.md`` contract.

    Returns:
        str: ``"no setup required"`` or ``"setup required"``.

    Examples:
        >>> from sevn.skills.manifest import SkillManifest
        >>> skill_setup_status(SkillManifest(name="x", description="d", version="1.0.0"))
        'no setup required'
    """
    if not manifest.dependencies.requires_setup:
        return "no setup required"
    return "setup required"


def skill_setup_requirements(manifest: SkillManifest) -> list[dict[str, Any]]:
    """Return structured setup rows for one manifest.

    Args:
        manifest (SkillManifest): Parsed ``SKILL.md`` contract.

    Returns:
        list[dict[str, Any]]: Rows with ``kind``, ``name``, ``satisfied``, and
            optional ``capability_id`` / ``message``.

    Examples:
        >>> from sevn.skills.manifest import SkillManifest
        >>> skill_setup_requirements(
        ...     SkillManifest(name="x", description="d", version="1.0.0"),
        ... )
        []
    """
    deps = manifest.dependencies
    if not deps.requires_setup:
        return []
    cap_index = _capability_index()
    rows: list[dict[str, Any]] = []
    for extra in deps.uv_extras:
        cap_id = cap_index.get(extra)
        rows.append(
            {
                "kind": "uv_extra",
                "name": extra,
                "capability_id": cap_id,
                "satisfied": _uv_extra_satisfied(extra),
            },
        )
    for exe in deps.executables:
        cap_id = cap_index.get(exe)
        rows.append(
            {
                "kind": "executable",
                "name": exe,
                "capability_id": cap_id,
                "satisfied": _executable_satisfied(exe),
            },
        )
    return rows


def skill_setup_telegram_summary(
    skill_id: str,
    manifest: SkillManifest,
) -> dict[str, Any]:
    """Return shared setup summary rows for CLI and Telegram form flows.

    Args:
        skill_id (str): Canonical skill id.
        manifest (SkillManifest): Parsed skill manifest.

    Returns:
        dict[str, Any]: ``lines``, ``unsupported``, ``unmet``, and ``needs_confirm`` keys.

    Examples:
        >>> from sevn.skills.manifest import SkillManifest
        >>> out = skill_setup_telegram_summary("x", SkillManifest(name="x", description="d", version="1.0.0"))
        >>> out["needs_confirm"] is False
        True
    """
    status = skill_setup_status(manifest)
    requirements = skill_setup_requirements(manifest)
    lines = [f"{skill_id}: {status}"]
    for row in requirements:
        mark = "ok" if row.get("satisfied") else "missing"
        lines.append(f"  [{mark}] {row.get('kind')} {row.get('name')}")
    unsupported = [
        row for row in requirements if not row.get("satisfied") and row.get("capability_id") is None
    ]
    unmet = [row for row in requirements if not row.get("satisfied")]
    needs_confirm = bool(unmet) and not unsupported
    return {
        "lines": lines,
        "requirements": requirements,
        "unsupported": unsupported,
        "unmet": unmet,
        "needs_confirm": needs_confirm,
    }


def execute_skill_setup(
    skill_id: str,
    *,
    workspace_root: Path,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Install or repair declared dependencies for one workspace skill.

    Args:
        skill_id (str): Canonical skill id.
        workspace_root (Path): Workspace content root.
        confirmed (bool): When ``False`` and installs would run, raises
            :class:`InstallConfirmationRequired`.

    Returns:
        dict[str, Any]: Result envelope with ``ok``, ``message``, and optional
            ``requirements``, ``reload_required``.

    Examples:
        >>> execute_skill_setup("missing", workspace_root=Path("/tmp"), confirmed=True)["ok"]
        False
    """
    from sevn.skills.manager import SkillsManager
    from sevn.workspace.layout import WorkspaceLayout

    layout = WorkspaceLayout(
        sevn_json_path=workspace_root / "sevn.json", content_root=workspace_root
    )
    skills_root = workspace_root / "skills"
    manager = SkillsManager.shared(workspace_root, (skills_root,), layout=layout)
    try:
        record = manager.get_record(skill_id)
    except SkillExecutionError as exc:
        return {"ok": False, "message": str(exc)}

    manifest = record.manifest
    requirements = skill_setup_requirements(manifest)
    if not requirements:
        return {
            "ok": True,
            "message": "no setup required",
            "requirements": requirements,
            "reload_required": False,
        }

    unsupported = [
        row for row in requirements if not row.get("satisfied") and row.get("capability_id") is None
    ]
    if unsupported:
        names = ", ".join(str(row["name"]) for row in unsupported)
        return {
            "ok": False,
            "message": (
                f"No automated setup is available for {names}. "
                "Install manually and ensure the executable is on PATH."
            ),
            "requirements": requirements,
            "reload_required": False,
        }

    unmet = [row for row in requirements if not row.get("satisfied")]
    if not unmet:
        return {
            "ok": True,
            "message": "all requirements already satisfied",
            "requirements": requirements,
            "reload_required": False,
        }

    if not confirmed:
        msg = "Skill setup requires operator confirmation — pass confirmed=True or use --yes"
        raise InstallConfirmationRequired(msg)

    capability_ids = {str(row["capability_id"]) for row in unmet if row.get("capability_id")}
    plan = build_install_plan_for_capability_ids(capability_ids)
    install_root = resolve_install_root()
    summary = asyncio.run(
        collect_install_run(
            plan,
            install_root=install_root,
            content_root=workspace_root,
        ),
    )
    manager.reload()
    requirements_after = skill_setup_requirements(manifest)
    still_unmet = [row for row in requirements_after if not row.get("satisfied")]
    ok = summary.ok and not still_unmet
    if ok:
        message = "setup complete"
    elif still_unmet:
        names = ", ".join(str(row["name"]) for row in still_unmet)
        message = f"setup finished with unmet requirements: {names}"
    else:
        message = "setup failed — see install logs"
    reload_required = any(row.get("kind") == "uv_extra" for row in unmet)
    return {
        "ok": ok,
        "message": message,
        "requirements": requirements_after,
        "reload_required": reload_required,
        "install_summary": summary.to_dict(),
    }


def _uv_extra_satisfied(extra: str) -> bool:
    """Return whether a uv extra import probe succeeds.

    Args:
        extra (str): Optional dependency extra name.

    Returns:
        bool: ``True`` when the packaged import probe succeeds.

    Examples:
        >>> isinstance(_uv_extra_satisfied("missing-extra"), bool)
        True
    """
    probe = UV_EXTRA_IMPORT_PROBE.get(extra)
    if probe is None:
        return False
    return _import_probe_satisfied(probe)


def _executable_satisfied(name: str) -> bool:
    """Return whether *name* resolves on the augmented operator PATH.

    Args:
        name (str): Executable basename to probe.

    Returns:
        bool: ``True`` when ``shutil.which`` finds the binary.

    Examples:
        >>> isinstance(_executable_satisfied("missing-binary-xyz"), bool)
        True
    """
    from sevn.runtime.operator_path import augment_operator_path

    env = augment_operator_path()
    return shutil.which(name, path=env.get("PATH")) is not None


def _import_probe_satisfied(probe: str) -> bool:
    """Run a one-liner import probe in the active interpreter.

    Args:
        probe (str): Python source passed to ``python -c``.

    Returns:
        bool: ``True`` when the subprocess exits zero.

    Examples:
        >>> _import_probe_satisfied("import sys")
        True
    """
    import subprocess  # nosec B404

    proc = subprocess.run(  # nosec B603
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _capability_index(manifest: CapabilityManifest | None = None) -> dict[str, str]:
    """Map uv-extra / executable names to onboarding capability ids.

    Args:
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        dict[str, str]: Requirement name to ``capability_id``.

    Examples:
        >>> "yt-dlp" in _capability_index()
        True
    """
    doc = manifest or load_manifest()
    uv_map: dict[str, str] = {}
    exe_map: dict[str, str] = {}
    for cap in doc.capabilities:
        for action in cap.install_actions:
            if action.kind != "uv_extra" or not action.argv:
                continue
            name = str(action.argv[0])
            current = uv_map.get(name)
            if current is None or cap.capability_id.startswith("extra."):
                uv_map[name] = cap.capability_id
            exe_map.setdefault(name, cap.capability_id)
    return {**uv_map, **exe_map}


__all__ = [
    "InstallConfirmationRequired",
    "execute_skill_setup",
    "skill_setup_requirements",
    "skill_setup_status",
    "skill_setup_telegram_summary",
]
