"""Onboarding capability install orchestrator (`plan/onboarding-comprehensive-setup` W6).

Module: sevn.onboarding.install_orchestrator
Depends: pathlib, sevn.onboarding.capabilities_manifest, sevn.onboarding.install_actions

Exports:
    InstallPlanStep — one capability-bound install action.
    InstallPlan — dry-run plan with fatal/warn counts.
    InstallRunSummary — aggregate result after execution.
    selected_capability_ids — derive enabled capabilities from merged config.
    resolve_install_root — sevn.bot checkout for ``uv`` / ``make``.
    build_install_plan — ordered plan from promoted ``sevn.json``.
    run_install_plan — async execute with JSON-line progress events.
    collect_install_run — drain ``run_install_plan`` into a summary dict.
    format_ndjson_event — encode one progress event as NDJSON.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sevn.onboarding.capabilities_manifest import (
    CapabilityEntry,
    CapabilityManifest,
    InstallAction,
    load_manifest,
)
from sevn.onboarding.install_actions.executors import execute_install_action


def _get_nested(doc: dict[str, Any], dotted: str) -> Any:
    """Read a dot-separated path from ``doc``.

    Args:
        doc (dict[str, Any]): Source document.
        dotted (str): Field id.

    Returns:
        Any: Value at path, or ``None`` when any segment is missing.

    Examples:
        >>> _get_nested({"gateway": {"port": 1}}, "gateway.port")
        1
    """
    cur: Any = doc
    for key in dotted.split("."):
        if not key or not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _capability_enabled(cap: CapabilityEntry, merged_config: dict[str, Any]) -> bool:
    """Return whether a manifest row is selected in the merged workspace document.

    Args:
        cap (CapabilityEntry): Manifest capability row.
        merged_config (dict[str, Any]): Merged ``sevn.json`` draft or promoted doc.

    Returns:
        bool: Whether install actions for this capability should run.

    Examples:
        >>> from sevn.onboarding.capabilities_manifest import load_manifest
        >>> m = load_manifest()
        >>> row = next(c for c in m.capabilities if c.capability_id == "extra.browser_cdp")
        >>> _capability_enabled(row, {"tools": {"browser": {"enabled": True}}})
        True
    """
    path = cap.config_paths[0]
    value = _get_nested(merged_config, path)
    if cap.control == "select":
        if value is None:
            return isinstance(cap.default, str) and bool(cap.default)
        return value is not None and str(value).strip() != ""
    if cap.control == "hidden":
        if value is None:
            return bool(cap.default)
        return bool(value)
    if value is None:
        return bool(cap.default) if isinstance(cap.default, bool) else False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def selected_capability_ids(
    merged_config: dict[str, Any],
    *,
    manifest: CapabilityManifest | None = None,
) -> set[str]:
    """Return capability ids enabled in the merged onboarding document.

    Args:
        merged_config (dict[str, Any]): Merged ``sevn.json`` tree.
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        set[str]: Selected capability ids before dependency expansion.

    Examples:
        >>> ids = selected_capability_ids({"tools": {"browser": {"enabled": True}}})
        >>> "extra.browser_cdp" in ids
        True
    """
    doc = manifest or load_manifest()
    return {
        cap.capability_id for cap in doc.capabilities if _capability_enabled(cap, merged_config)
    }


def _expand_dependencies(selected: set[str], manifest: CapabilityManifest) -> set[str]:
    """Add transitive ``depends_on`` capabilities required by the selection.

    Args:
        selected (set[str]): Operator-selected capability ids.
        manifest (CapabilityManifest): Loaded manifest.

    Returns:
        set[str]: Expanded id set including dependencies.

    Examples:
        >>> m = load_manifest()
        >>> expanded = _expand_dependencies({"code_understanding.graphify"}, m)
        >>> "extra.graphify" in expanded
        True
    """
    index = {row.capability_id: row for row in manifest.capabilities}
    expanded = set(selected)
    changed = True
    while changed:
        changed = False
        for cid in list(expanded):
            row = index.get(cid)
            if row is None:
                continue
            for dep in row.depends_on or []:
                if dep not in expanded:
                    expanded.add(dep)
                    changed = True
    return expanded


def resolve_install_root(
    merged_config: dict[str, Any] | None = None,
    *,
    content_root: Path | None = None,
) -> Path:
    """Resolve the sevn.bot checkout used for ``uv sync`` and ``make`` targets.

    Args:
        merged_config (dict[str, Any] | None): Workspace document for ``my_sevn`` hints.
        content_root (Path | None): Operator workspace content root.

    Returns:
        Path: Repository root containing ``pyproject.toml``.

    Examples:
        >>> root = resolve_install_root()
        >>> (root / "pyproject.toml").is_file()
        True
    """
    from sevn.config.sevn_repo import resolve_sevn_checkout_with_origin
    from sevn.config.workspace_config import parse_workspace_config

    cfg = parse_workspace_config(merged_config) if merged_config else None
    checkout, _origin = resolve_sevn_checkout_with_origin(
        content_root=content_root,
        workspace=cfg,
    )
    if checkout is not None:
        return checkout
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "sevn").is_dir():
            return parent
    return Path.cwd()


@dataclass(frozen=True, slots=True)
class InstallPlanStep:
    """One install action bound to its owning capability."""

    capability_id: str
    action: InstallAction


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Dry-run install plan returned by ``build_install_plan``."""

    steps: tuple[InstallPlanStep, ...]
    fatal_count: int
    warn_count: int
    selected_capability_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for ``POST /api/install-plan`` responses.

        Returns:
            dict[str, Any]: JSON-serializable plan body.

        Examples:
            >>> plan = build_install_plan({"skills": {"browser": {"enabled": True}}})
            >>> "steps" in plan.to_dict()
            True
        """
        return {
            "steps": [
                {
                    "capability_id": step.capability_id,
                    "action": step.action.model_dump(mode="json"),
                }
                for step in self.steps
            ],
            "fatal_count": self.fatal_count,
            "warn_count": self.warn_count,
            "selected_capability_ids": list(self.selected_capability_ids),
        }


@dataclass(frozen=True, slots=True)
class InstallRunSummary:
    """Aggregate outcome after running an install plan."""

    ok: bool
    fatal_failed: bool
    events: tuple[dict[str, Any], ...]
    failed_fatal_action_ids: tuple[str, ...]
    skipped_action_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for ``POST /api/save`` install metadata.

        Returns:
            dict[str, Any]: JSON-serializable summary.

        Examples:
            >>> InstallRunSummary(True, False, (), (), ()).to_dict()["ok"]
            True
        """
        return {
            "ok": self.ok,
            "fatal_failed": self.fatal_failed,
            "failed_fatal_action_ids": list(self.failed_fatal_action_ids),
            "skipped_action_ids": list(self.skipped_action_ids),
            "events": list(self.events),
        }


def build_install_plan(
    merged_config: dict[str, Any],
    *,
    manifest: CapabilityManifest | None = None,
) -> InstallPlan:
    """Build an ordered install plan from a merged workspace document.

    Args:
        merged_config (dict[str, Any]): Merged ``sevn.json`` draft or promoted doc.
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        InstallPlan: Dependency-safe steps with fatal/warn counts.

    Examples:
        >>> plan = build_install_plan({"skills": {"browser": {"enabled": True}}})
        >>> plan.fatal_count >= 1
        True
    """
    doc = manifest or load_manifest()
    selected = _expand_dependencies(selected_capability_ids(merged_config, manifest=doc), doc)
    index = {row.capability_id: row for row in doc.capabilities}

    indegree: dict[str, int] = {cid: 0 for cid in selected}
    adj: dict[str, list[str]] = {cid: [] for cid in selected}
    for cid in selected:
        cap = index[cid]
        for dep in cap.depends_on or []:
            if dep in selected:
                adj[dep].append(cid)
                indegree[cid] += 1

    from collections import deque

    queue: deque[str] = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
    cap_order: list[str] = []
    while queue:
        node = queue.popleft()
        cap_order.append(node)
        for nxt in sorted(adj[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    seen_action_ids: set[str] = set()
    steps: list[InstallPlanStep] = []
    for cid in cap_order:
        for action in index[cid].install_actions:
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
        selected_capability_ids=tuple(sorted(selected)),
    )


async def run_install_plan(
    plan: InstallPlan,
    *,
    install_root: Path | None = None,
    merged_config: dict[str, Any] | None = None,
    content_root: Path | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Execute ``plan`` and yield W0.5 JSON-line progress events.

    Args:
        plan (InstallPlan): Plan from :func:`build_install_plan`.
        install_root (Path | None): sevn.bot checkout; resolved when omitted.
        merged_config (dict[str, Any] | None): Promoted workspace document.
        content_root (Path | None): Workspace content root for secret checks.

    Returns:
        AsyncIterator[dict[str, Any]]: Progress events (`start`, `log`, `end`).

    Examples:
        >>> import asyncio
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> noop_plan = InstallPlan(
        ...     (InstallPlanStep("t", InstallAction(id="t.n", kind="noop", argv=[], fatal=False)),),
        ...     0,
        ...     1,
        ...     ("t",),
        ... )
        >>> events = asyncio.run(_drain(run_install_plan(noop_plan)))
        >>> events[-1]["status"]
        'ok'
    """
    root = install_root or resolve_install_root(merged_config, content_root=content_root)
    for step in plan.steps:
        async for event in execute_install_action(
            step.action,
            install_root=root,
            capability_id=step.capability_id,
            merged_config=merged_config,
            content_root=content_root,
        ):
            yield event


async def collect_install_run(
    plan: InstallPlan,
    *,
    install_root: Path | None = None,
    merged_config: dict[str, Any] | None = None,
    content_root: Path | None = None,
) -> InstallRunSummary:
    """Run ``plan`` and return an aggregate summary for JSON APIs.

    Args:
        plan (InstallPlan): Plan to execute.
        install_root (Path | None): sevn.bot checkout root.
        merged_config (dict[str, Any] | None): Promoted workspace document.
        content_root (Path | None): Workspace content root.

    Returns:
        InstallRunSummary: ok/fatal flags and captured events.

    Examples:
        >>> import asyncio
        >>> from sevn.onboarding.capabilities_manifest import InstallAction
        >>> plan = InstallPlan(
        ...     (InstallPlanStep("t", InstallAction(id="t.n", kind="noop", argv=[], fatal=False)),),
        ...     0,
        ...     1,
        ...     ("t",),
        ... )
        >>> summary = asyncio.run(collect_install_run(plan))
        >>> summary.ok
        True
    """
    events: list[dict[str, Any]] = []
    failed_fatal: list[str] = []
    skipped: list[str] = []
    async for event in run_install_plan(
        plan,
        install_root=install_root,
        merged_config=merged_config,
        content_root=content_root,
    ):
        events.append(event)
        if event.get("type") == "end":
            if event.get("status") == "skipped":
                skipped.append(str(event.get("action_id", "")))
            elif event.get("status") == "failed" and event.get("fatal"):
                failed_fatal.append(str(event.get("action_id", "")))
    fatal_failed = bool(failed_fatal)
    ok = not fatal_failed
    return InstallRunSummary(
        ok=ok,
        fatal_failed=fatal_failed,
        events=tuple(events),
        failed_fatal_action_ids=tuple(failed_fatal),
        skipped_action_ids=tuple(skipped),
    )


def format_ndjson_event(event: dict[str, Any]) -> str:
    """Encode one progress event as an NDJSON line.

    Args:
        event (dict[str, Any]): Progress payload.

    Returns:
        str: Single JSON object plus newline.

    Examples:
        >>> format_ndjson_event({"type": "start", "action_id": "a"})
        '{"type":"start","action_id":"a"}\\n'
    """
    return json.dumps(event, separators=(",", ":")) + "\n"


async def _drain(gen: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect async iterator events (internal helper).

    Args:
        gen (AsyncIterator[dict[str, Any]]): Progress event stream.

    Returns:
        list[dict[str, Any]]: Drained events.

    Examples:
        >>> import asyncio
        >>> async def _one() -> AsyncIterator[dict[str, Any]]:
        ...     yield {"type": "end", "status": "ok"}
        ...     return
        ...     yield  # pragma: no cover
        >>> asyncio.run(_drain(_one()))[0]["status"]
        'ok'
    """
    out: list[dict[str, Any]] = []
    async for item in gen:
        out.append(item)
    return out


__all__ = [
    "InstallPlan",
    "InstallPlanStep",
    "InstallRunSummary",
    "build_install_plan",
    "collect_install_run",
    "format_ndjson_event",
    "resolve_install_root",
    "run_install_plan",
    "selected_capability_ids",
]
