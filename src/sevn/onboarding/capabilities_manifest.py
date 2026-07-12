"""Onboarding capability manifest loader (`specs/22-onboarding.md` comprehensive setup W1).

Module: sevn.onboarding.capabilities_manifest
Depends: importlib.resources, json, pydantic, typing

Exports:
    InstallAction — one install step from the manifest protocol.
    CapabilityEntry — manifest row (checkbox, select, or hidden).
    CapabilityGroup — grouped wizard section A-G.
    CapabilityManifest — full ``onboarding_capabilities.json`` document.
    GroupWithCapabilities — group row plus nested capabilities for API responses.
    load_manifest — parse and validate the packaged manifest.
    list_groups — return groups with nested capabilities.
    resolve_install_plan — ordered install actions for selected capabilities.
    merged_capability_defaults — profile-aware default values for the wizard.
    skill_capability_id — map INDEX skill name to ``skill.<snake>`` id.
    index_skill_capability_ids — INDEX name to capability_id map.
    manifest_resource_path — packaged JSON filename.

Examples:
    >>> manifest = load_manifest()
    >>> manifest.schema_version
    1
    >>> groups = list_groups()
    >>> {g.id for g in groups} == {"A", "B", "C", "D", "E", "F", "G"}
    True
"""

from __future__ import annotations

import json
from collections import deque
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sevn.data.skills_index import read_skills_index

InstallActionKind = Literal[
    "uv_extra",
    "subprocess",
    "make_target",
    "noop",
    "secret_required",
    "second_brain_bootstrap",
]
ControlType = Literal["checkbox", "select", "hidden", "text", "folder_picker"]
GroupId = Literal["A", "B", "C", "D", "E", "F", "G"]


class InstallAction(BaseModel):
    """Single install action (`plan/onboarding-comprehensive-setup` W0.5 protocol)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: InstallActionKind
    argv: list[str]
    fatal: bool
    note: str | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None
    idempotent_check: str | None = None


class CapabilityEntry(BaseModel):
    """One wizard capability row from ``onboarding_capabilities.json``."""

    model_config = ConfigDict(extra="forbid")

    capability_id: str
    group: GroupId
    label: str
    description: str
    config_paths: list[str] = Field(min_length=1)
    control: ControlType
    default: bool | str
    profile_overridable: bool
    install_actions: list[InstallAction]
    select_options: list[str] | None = None
    depends_on: list[str] | None = None
    wizard_tab: str | None = None

    @field_validator("select_options")
    @classmethod
    def _select_requires_options(cls, v: list[str] | None, info: Any) -> list[str] | None:
        """Require ``select_options`` when ``control`` is ``select``.

        Args:
            cls (type): Model class.
            v (list[str] | None): Parsed select options.
            info (Any): Pydantic validation info.

        Returns:
            list[str] | None: Validated options.

        Raises:
            ValueError: When control is select but options are missing.

        Examples:
            >>> CapabilityEntry._select_requires_options(["cancel"], type("I", (), {"data": {"control": "select"}})())
            ['cancel']
        """
        control = info.data.get("control")
        if control == "select" and not v:
            msg = "select_options required when control is select"
            raise ValueError(msg)
        return v


class CapabilityGroup(BaseModel):
    """Manifest group metadata (A-G)."""

    model_config = ConfigDict(extra="forbid")

    id: GroupId
    label: str
    description: str = ""
    sort_order: int = Field(ge=1, le=7)


class CapabilityManifest(BaseModel):
    """Top-level onboarding capability manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    groups: list[CapabilityGroup] = Field(min_length=7, max_length=7)
    capabilities: list[CapabilityEntry] = Field(min_length=1)


class GroupWithCapabilities(BaseModel):
    """Group row plus nested capabilities for API responses."""

    model_config = ConfigDict(extra="forbid")

    id: GroupId
    label: str
    description: str
    sort_order: int
    capabilities: list[dict[str, Any]]


def skill_capability_id(skill_name: str) -> str:
    """Return manifest ``capability_id`` for a bundled skill INDEX name.

    Args:
        skill_name (str): Kebab or snake skill name from ``skills/INDEX.md``.

    Returns:
        str: ``skill.<snake_name>`` id.

    Examples:
        >>> skill_capability_id("computer-use")
        'skill.computer_use'
        >>> skill_capability_id("cua-agent")
        'skill.cua_agent'
        >>> skill_capability_id("lume")
        'skill.lume'
        >>> skill_capability_id("graphify")
        'skill.graphify'
    """
    return f"skill.{skill_name.replace('-', '_')}"


def manifest_resource_path() -> str:
    """Return packaged manifest filename.

    Returns:
        str: Resource name under ``sevn.data``.

    Examples:
        >>> manifest_resource_path()
        'onboarding_capabilities.json'
    """
    return "onboarding_capabilities.json"


def load_manifest() -> CapabilityManifest:
    """Load and validate ``onboarding_capabilities.json``.

    Returns:
        CapabilityManifest: Parsed manifest.

    Raises:
        FileNotFoundError: When packaged data is missing.
        ValueError: When JSON is invalid.

    Examples:
        >>> m = load_manifest()
        >>> any(c.capability_id == "gateway.queue_mode" for c in m.capabilities)
        True
    """
    ref = resources.files("sevn.data") / manifest_resource_path()
    raw = json.loads(ref.read_text(encoding="utf-8"))
    return CapabilityManifest.model_validate(raw)


def _capability_index(manifest: CapabilityManifest) -> dict[str, CapabilityEntry]:
    """Build ``capability_id`` → row lookup for a manifest.

    Args:
        manifest (CapabilityManifest): Loaded manifest document.

    Returns:
        dict[str, CapabilityEntry]: Capability rows keyed by id.

    Examples:
        >>> m = load_manifest()
        >>> idx = _capability_index(m)
        >>> "gateway.queue_mode" in idx
        True
    """
    return {row.capability_id: row for row in manifest.capabilities}


def list_groups(manifest: CapabilityManifest | None = None) -> list[GroupWithCapabilities]:
    """Return manifest groups with nested capability rows.

    Args:
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        list[GroupWithCapabilities]: Groups sorted by ``sort_order``.

    Examples:
        >>> rows = list_groups()
        >>> rows[0].id == "A"
        True
    """
    doc = manifest or load_manifest()
    by_group: dict[str, list[CapabilityEntry]] = {g.id: [] for g in doc.groups}
    for cap in doc.capabilities:
        by_group[cap.group].append(cap)
    out: list[GroupWithCapabilities] = []
    for group in sorted(doc.groups, key=lambda g: g.sort_order):
        caps = sorted(by_group[group.id], key=lambda c: c.capability_id)
        out.append(
            GroupWithCapabilities(
                id=group.id,
                label=group.label,
                description=group.description,
                sort_order=group.sort_order,
                capabilities=[c.model_dump(mode="json") for c in caps],
            )
        )
    return out


def merged_capability_defaults(
    *,
    profile_fragment: dict[str, Any] | None = None,
    manifest: CapabilityManifest | None = None,
) -> dict[str, bool | str]:
    """Resolve wizard defaults with optional profile ``capabilities_defaults``.

    Args:
        profile_fragment (dict[str, Any] | None): Profile overlay JSON.
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        dict[str, bool | str]: ``capability_id`` → effective default.

    Examples:
        >>> defaults = merged_capability_defaults()
        >>> isinstance(defaults.get("gateway.queue_mode"), str)
        True
    """
    doc = manifest or load_manifest()
    overrides: dict[str, bool] = {}
    if profile_fragment:
        raw = profile_fragment.get("capabilities_defaults")
        if isinstance(raw, dict):
            overrides = {str(k): bool(v) for k, v in raw.items()}
    merged: dict[str, bool | str] = {}
    for cap in doc.capabilities:
        value: bool | str = cap.default
        if cap.profile_overridable and cap.capability_id in overrides:
            value = overrides[cap.capability_id]
        merged[cap.capability_id] = value
    return merged


def resolve_install_plan(
    selected_ids: set[str] | list[str],
    merged_config: dict[str, Any] | None = None,
    *,
    manifest: CapabilityManifest | None = None,
) -> list[InstallAction]:
    """Return ordered, deduplicated install actions for selected capabilities.

    Topological order respects ``depends_on`` edges. ``merged_config`` is reserved
    for W6 conditional actions (e.g. sandbox mode); W1 returns static actions.

    Args:
        selected_ids (set[str] | list[str]): Operator-selected capability ids.
        merged_config (dict[str, Any] | None): Merged ``sevn.json`` draft (unused in W1).
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        list[InstallAction]: Actions in dependency-safe order.

    Raises:
        ValueError: When an unknown id is selected or dependencies are cyclic.

    Examples:
        >>> plan = resolve_install_plan(["extra.browser"])
        >>> plan[0].kind in ("uv_extra", "subprocess", "noop")
        True
    """
    _ = merged_config
    doc = manifest or load_manifest()
    index = _capability_index(doc)
    wanted = {str(i) for i in selected_ids}
    unknown = sorted(wanted - set(index))
    if unknown:
        msg = f"unknown capability_id(s): {', '.join(unknown)}"
        raise ValueError(msg)

    # Kahn topological sort on depends_on within the selected subgraph.
    indegree: dict[str, int] = {cid: 0 for cid in wanted}
    adj: dict[str, list[str]] = {cid: [] for cid in wanted}
    for cid in wanted:
        cap = index[cid]
        for dep in cap.depends_on or []:
            if dep not in wanted:
                continue
            if dep not in index:
                msg = f"capability {cid!r} depends on unknown {dep!r}"
                raise ValueError(msg)
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

    seen_action_ids: set[str] = set()
    plan: list[InstallAction] = []
    for cid in ordered:
        for action in index[cid].install_actions:
            if action.id in seen_action_ids:
                continue
            seen_action_ids.add(action.id)
            plan.append(action)
    return plan


def index_skill_capability_ids(manifest: CapabilityManifest | None = None) -> dict[str, str]:
    """Map INDEX skill name → manifest ``skill.*`` capability id.

    Args:
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        dict[str, str]: INDEX name to capability_id.

    Examples:
        >>> mapping = index_skill_capability_ids()
        >>> mapping["graphify"]
        'skill.graphify'
    """
    doc = manifest or load_manifest()
    out: dict[str, str] = {}
    for cap in doc.capabilities:
        if cap.capability_id.startswith("skill."):
            skill_name = cap.capability_id.removeprefix("skill.").replace("_", "-")
            # Prefer exact INDEX names (some use underscores).
            for name in read_skills_index():
                if skill_capability_id(name) == cap.capability_id:
                    out[name] = cap.capability_id
                    break
            else:
                out[skill_name] = cap.capability_id
    return out


__all__ = [
    "CapabilityEntry",
    "CapabilityGroup",
    "CapabilityManifest",
    "ControlType",
    "GroupId",
    "GroupWithCapabilities",
    "InstallAction",
    "InstallActionKind",
    "index_skill_capability_ids",
    "list_groups",
    "load_manifest",
    "manifest_resource_path",
    "merged_capability_defaults",
    "resolve_install_plan",
    "skill_capability_id",
]
