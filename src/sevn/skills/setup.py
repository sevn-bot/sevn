"""Skill dependency setup orchestration (issues #69 / #93, ``specs/12-skills-system.md``).

Module: sevn.skills.setup
Depends: asyncio, pathlib, shutil, sevn.onboarding.install_orchestrator

Exports:
    InstallConfirmationRequired — raised when install runs without operator confirm.
    skill_setup_status — coarse setup state for one manifest.
    skill_setup_requirements — structured unmet rows for CLI/Telegram.
    execute_skill_setup — install/repair one skill's declared dependencies.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

from sevn.onboarding.capabilities_manifest import CapabilityManifest, InstallAction, load_manifest
from sevn.onboarding.install_actions.executors import execute_install_action
from sevn.onboarding.install_orchestrator import (
    InstallPlan,
    InstallPlanStep,
    InstallRunSummary,
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
    rows: list[dict[str, Any]] = []
    for extra in deps.uv_extras:
        cap_id = _capability_for_uv_extra(extra)
        rows.append(
            {
                "kind": "uv_extra",
                "name": extra,
                "capability_id": cap_id,
                "satisfied": _uv_extra_satisfied(extra),
            },
        )
    for exe in deps.executables:
        cap_id = _capability_for_executable(exe)
        rows.append(
            {
                "kind": "executable",
                "name": exe,
                "capability_id": cap_id,
                "satisfied": _executable_satisfied(exe),
            },
        )
    return rows


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
    plan = _build_install_plan_for_capabilities(capability_ids)
    install_root = resolve_install_root()
    summary = _run_skill_install_plan(
        plan,
        install_root=install_root,
        content_root=workspace_root,
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
    import subprocess

    proc = subprocess.run(
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


def _capability_for_uv_extra(extra: str) -> str | None:
    """Resolve one uv extra name to a capability id.

    Args:
        extra (str): Extra name from skill frontmatter.

    Returns:
        str | None: Matching capability id when known.

    Examples:
        >>> _capability_for_uv_extra("job-ops") is not None
        True
    """
    return _capability_index().get(extra)


def _capability_for_executable(name: str) -> str | None:
    """Resolve one executable name to a capability id.

    Args:
        name (str): Executable basename from skill frontmatter.

    Returns:
        str | None: Matching capability id when known.

    Examples:
        >>> _capability_for_executable("yt-dlp") is not None
        True
    """
    return _capability_index().get(name)


def _capability_order(capability_ids: set[str]) -> list[str]:
    """Topologically sort capability ids for install ordering.

    Args:
        capability_ids (set[str]): Selected capability ids.

    Returns:
        list[str]: Dependency-safe capability order.

    Raises:
        ValueError: When ids are unknown or cyclic.

    Examples:
        >>> _capability_order({"skill.job_ops"}) == ["skill.job_ops"]
        True
    """
    from collections import deque

    doc = load_manifest()
    index = {row.capability_id: row for row in doc.capabilities}
    wanted = set(capability_ids)
    unknown = sorted(wanted - set(index))
    if unknown:
        msg = f"unknown capability_id(s): {', '.join(unknown)}"
        raise ValueError(msg)

    indegree: dict[str, int] = {cid: 0 for cid in wanted}
    adj: dict[str, list[str]] = {cid: [] for cid in wanted}
    for cid in wanted:
        cap = index[cid]
        for dep in cap.depends_on or []:
            if dep not in wanted:
                continue
            adj[dep].append(cid)
            indegree[cid] += 1

    queue: deque[str] = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
    ordered: list[str] = []
    while queue:
        node = queue.popleft()
        ordered.append(node)
        for nxt in sorted(adj[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(ordered) != len(wanted):
        msg = "cyclic capability depends_on graph"
        raise ValueError(msg)
    return ordered


def _build_install_plan_for_capabilities(capability_ids: set[str]) -> InstallPlan:
    """Build an onboarding install plan for selected capability ids.

    Args:
        capability_ids (set[str]): Selected capability ids.

    Returns:
        InstallPlan: Ordered install steps excluding noop actions.

    Examples:
        >>> plan = _build_install_plan_for_capabilities({"skill.job_ops"})
        >>> len(plan.steps) >= 1
        True
    """
    doc = load_manifest()
    index = {row.capability_id: row for row in doc.capabilities}
    ordered = _capability_order(capability_ids)
    seen_action_ids: set[str] = set()
    steps: list[InstallPlanStep] = []
    for cid in ordered:
        for action in index[cid].install_actions:
            if action.kind == "noop":
                continue
            if action.id in seen_action_ids:
                continue
            seen_action_ids.add(action.id)
            steps.append(InstallPlanStep(capability_id=cid, action=action))
    fatal_count = sum(1 for step in steps if step.action.fatal)
    warn_count = len(steps) - fatal_count
    return InstallPlan(
        steps=tuple(steps),
        fatal_count=fatal_count,
        warn_count=warn_count,
        selected_capability_ids=tuple(sorted(capability_ids)),
    )


def _checkout_has_dev_group(install_root: Path) -> bool:
    """Return whether the checkout ``pyproject.toml`` declares a dev group.

    Args:
        install_root (Path): sevn.bot checkout root.

    Returns:
        bool: ``True`` when a dev dependency group is declared.

    Examples:
        >>> isinstance(_checkout_has_dev_group(Path(".")), bool)
        True
    """
    pyproject = install_root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    text = pyproject.read_text(encoding="utf-8")
    return "\ndev = [" in text or text.startswith("dev = [")


def _uv_sync_argv(action: InstallAction, *, install_root: Path) -> list[str]:
    """Return ``uv sync`` argv for one uv-extra install action.

    Args:
        action (InstallAction): Manifest uv-extra action.
        install_root (Path): sevn.bot checkout root.

    Returns:
        list[str]: argv for ``subprocess.run``.

    Examples:
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> act = InstallAction(id="t", kind="uv_extra", argv=["job-ops"], fatal=False)
        >>> _uv_sync_argv(act, install_root=Path("."))[1]
        'sync'
    """
    argv = ["uv", "sync", "--extra", *action.argv]
    if _checkout_has_dev_group(install_root):
        argv.extend(["--group", "dev"])
    return argv


def _run_skill_install_plan(
    plan: InstallPlan,
    *,
    install_root: Path,
    content_root: Path,
) -> InstallRunSummary:
    """Execute a skill setup install plan and return an aggregate summary.

    Args:
        plan (InstallPlan): Plan to execute.
        install_root (Path): sevn.bot checkout root.
        content_root (Path): Workspace content root.

    Returns:
        InstallRunSummary: Aggregate ok/fatal flags and captured events.

    Examples:
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> from sevn.onboarding.install_orchestrator import InstallPlan, InstallPlanStep
        >>> empty = InstallPlan((), 0, 0, ())
        >>> _run_skill_install_plan(empty, install_root=Path("."), content_root=Path(".")).ok
        True
    """
    import subprocess

    events: list[dict[str, Any]] = []
    failed_fatal: list[str] = []
    skipped: list[str] = []
    for step in plan.steps:
        action = step.action
        if action.kind == "uv_extra":
            argv = _uv_sync_argv(action, install_root=install_root)
            events.append(
                {
                    "type": "start",
                    "action_id": action.id,
                    "capability_id": step.capability_id,
                },
            )
            proc = subprocess.run(
                argv,
                cwd=install_root,
                capture_output=True,
                text=True,
            )
            if proc.stdout:
                for line in proc.stdout.splitlines():
                    events.append(
                        {
                            "type": "log",
                            "action_id": action.id,
                            "line": line,
                        },
                    )
            if proc.stderr:
                for line in proc.stderr.splitlines():
                    events.append(
                        {
                            "type": "log",
                            "action_id": action.id,
                            "line": line,
                        },
                    )
            status = "ok" if proc.returncode == 0 else "failed"
            events.append(
                {
                    "type": "end",
                    "action_id": action.id,
                    "status": status,
                    "exit_code": proc.returncode,
                    "fatal": action.fatal,
                },
            )
            if status == "failed" and action.fatal:
                failed_fatal.append(action.id)
            continue
        events.extend(
            asyncio.run(
                _collect_install_action_events(
                    action,
                    install_root=install_root,
                    capability_id=step.capability_id,
                    content_root=content_root,
                ),
            ),
        )
        end = next((event for event in reversed(events) if event.get("type") == "end"), None)
        if end is not None:
            if end.get("status") == "skipped":
                skipped.append(str(end.get("action_id", "")))
            elif end.get("status") == "failed" and end.get("fatal"):
                failed_fatal.append(str(end.get("action_id", "")))
    fatal_failed = bool(failed_fatal)
    ok = not fatal_failed
    return InstallRunSummary(
        ok=ok,
        fatal_failed=fatal_failed,
        events=tuple(events),
        failed_fatal_action_ids=tuple(failed_fatal),
        skipped_action_ids=tuple(skipped),
    )


async def _collect_install_action_events(
    action: InstallAction,
    *,
    install_root: Path,
    capability_id: str,
    content_root: Path,
) -> list[dict[str, Any]]:
    """Drain one async install action into a list of progress events.

    Args:
        action (InstallAction): Manifest install step.
        install_root (Path): sevn.bot checkout root.
        capability_id (str): Owning capability id.
        content_root (Path): Workspace content root.

    Returns:
        list[dict[str, Any]]: Progress events emitted by the action.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_collect_install_action_events)
        True
    """
    events: list[dict[str, Any]] = []
    async for event in execute_install_action(
        action,
        install_root=install_root,
        capability_id=capability_id,
        content_root=content_root,
    ):
        events.append(event)
    return events


__all__ = [
    "InstallConfirmationRequired",
    "execute_skill_setup",
    "skill_setup_requirements",
    "skill_setup_status",
]
