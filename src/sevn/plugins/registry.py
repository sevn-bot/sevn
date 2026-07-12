"""Entry-point discovery for ``sevn.plugin_hooks`` / ``sevn.channels`` (`specs/34-plugin-hooks.md` §2.4).
Module: sevn.plugins.registry
Depends: importlib.metadata
Exports:
    ChannelPluginSpec — class object loaded from ``sevn.channels``.
    DashboardBadgeEntry — stub registry row for ``sevn.dashboard_badges``.
    collect_plugin_slash_bindings — normalized slash rows with trust flags.
    load_channel_plugin_classes — optional third-party adapters.
    load_dashboard_badge_entries — enumerate ``sevn.dashboard_badges`` (v1 stub).
    load_plugin_hook_chain — workspace-gated hook list + chain object.
    valid_hook_name — namespace gate for ``PluginHook.name`` strings.
    order_hooks_by_runs_after — stable topo sort using ``runs_after`` hints.
    build_trigger_mux — multiplex ``TriggerPluginHookSurface`` for triggers.
"""

from __future__ import annotations

import heapq
import importlib.metadata
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.config.workspace_config import PluginHookEntryConfig, WorkspaceConfig
from sevn.plugins.command_spec import PluginCommandSpec, PluginSlashBinding
from sevn.plugins.hook import PluginHook, PluginHookBase
from sevn.plugins.runner import PluginHookChain, RegisteredHook
from sevn.plugins.trigger_mux import TriggerPluginHooksMux

if TYPE_CHECKING:
    from sevn.config.settings import ProcessSettings
_HOOK_NAME_RE = re.compile(r"^(?!__core__)[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*$")


def valid_hook_name(name: str) -> bool:
    """Return True when ``name`` obeys plugin namespace rules (`specs/34-plugin-hooks.md` §2.4).
    Args:
        name (str): ``PluginHook.name`` value.
    Returns:
        bool: Acceptance verdict.
    Examples:
        >>> valid_hook_name("acme.demo.tool")
        True
        >>> valid_hook_name("nope")
        False
    """
    return bool(_HOOK_NAME_RE.match(name))


def _policy(workspace: WorkspaceConfig, plugin_id: str) -> PluginHookEntryConfig:
    """Return merged ``plugin_hooks.<plugin_id>`` policy row.
    Args:
        workspace (WorkspaceConfig): Parsed workspace document.
        plugin_id (str): Entry-point / plugin id key.
    Returns:
        PluginHookEntryConfig: Typed policy object (defaults when absent).
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _policy(WorkspaceConfig.minimal(), "acme")
        PluginHookEntryConfig(...)
    """
    if workspace.plugin_hooks and plugin_id in workspace.plugin_hooks:
        return workspace.plugin_hooks[plugin_id]
    return PluginHookEntryConfig()


def _instantiate_hook(raw: object) -> PluginHook:
    """Coerce an entry-point object into a :class:`~sevn.plugins.hook.PluginHook`.
    Args:
        raw (object): Callable factory or already-constructed hook.
    Returns:
        PluginHook: Validated instance.
    Raises:
        TypeError: When the value is not a :class:`~sevn.plugins.hook.PluginHook`.
    Examples:
        >>> from sevn.plugins.hook import PluginHookBase
        >>> h = PluginHookBase("acme.demo.h")
        >>> _instantiate_hook(lambda: h) is h
        True
    """
    inst = raw() if callable(raw) else raw
    if not isinstance(inst, PluginHook):
        msg = f"plugin hook entry point must yield PluginHook, got {type(inst)}"
        raise TypeError(msg)
    return inst


def _distribution_key(ep: importlib.metadata.EntryPoint) -> str:
    """Return a stable distribution label for ordering and diagnostics.
    Args:
        ep (importlib.metadata.EntryPoint): Loaded entry point metadata.
    Returns:
        str: Distribution ``Name`` when present, otherwise ``ep.name``.
    Examples:
        >>> import importlib.metadata
        >>> ep = importlib.metadata.EntryPoint(name="x", value="pkg:obj", group="g")
        >>> isinstance(_distribution_key(ep), str)
        True
    """
    dist = ep.dist
    if dist is not None:
        return str(dist.metadata["Name"])
    return ep.name


def _hook_overrides_method(hook: PluginHook, method_name: str) -> bool:
    """Return True when ``hook`` overrides a :class:`PluginHookBase` default.
    Args:
        hook (PluginHook): Loaded plugin instance.
        method_name (str): Method name on the hook protocol.
    Returns:
        bool: ``True`` when the concrete class defines its own implementation.
    Examples:
        >>> from sevn.plugins.hook import PluginHookBase
        >>> _hook_overrides_method(PluginHookBase("acme.demo.h"), "pre_tool_call")
        False
    """
    base = getattr(PluginHookBase, method_name, None)
    impl = getattr(type(hook), method_name, None)
    return impl is not None and impl is not base


def _validate_default_trust_capabilities(hook: PluginHook, plugin_id: str) -> None:
    """Fail fast when ``default`` trust hooks implement owner-only surfaces.
    Args:
        hook (PluginHook): Loaded plugin instance.
        plugin_id (str): Workspace ``plugin_hooks`` key.
    Raises:
        RuntimeError: When a disallowed method is implemented under default trust.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_validate_default_trust_capabilities)
        True
    """
    if _hook_overrides_method(hook, "pre_tool_call"):
        msg = (
            f"plugin_hooks.{plugin_id}: pre_tool_call requires trust_level=owner "
            f"(default trust disallows pre_tool_call — raise trust_level or remove hook)"
        )
        raise RuntimeError(msg)
    if _hook_overrides_method(hook, "dispatch_tool"):
        msg = (
            f"plugin_hooks.{plugin_id}: dispatch_tool requires trust_level=owner "
            f"(default trust disallows dispatch_tool)"
        )
        raise RuntimeError(msg)


def order_hooks_by_runs_after(
    primary: list[RegisteredHook],
    workspace: WorkspaceConfig,
) -> tuple[RegisteredHook, ...]:
    """Stable topological order honoring per-plugin ``runs_after`` hints.
    Args:
        primary (list[RegisteredHook]): Lexicographically sorted hooks.
        workspace (WorkspaceConfig): Workspace containing hint lists.
    Returns:
        tuple[RegisteredHook, ...]: Execution order.
    Raises:
        RuntimeError: When hints form a cycle.
    Examples:
        >>> order_hooks_by_runs_after([], WorkspaceConfig.minimal())
        ()
    """
    by_name = {r.hook.name: r for r in primary}
    idx = {r.hook.name: i for i, r in enumerate(primary)}
    children: dict[str, list[str]] = {r.hook.name: [] for r in primary}
    indegree: dict[str, int] = {r.hook.name: 0 for r in primary}
    for r in primary:
        pol = workspace.plugin_hooks.get(r.plugin_id) if workspace.plugin_hooks else None
        hints = list(pol.runs_after) if pol and pol.runs_after else []
        for pred in hints:
            if pred not in indegree or pred == r.hook.name:
                continue
            children[pred].append(r.hook.name)
            indegree[r.hook.name] += 1
    heap: list[tuple[int, str]] = []
    for name, deg in indegree.items():
        if deg == 0:
            heapq.heappush(heap, (idx[name], name))
    out: list[RegisteredHook] = []
    while heap:
        _, n = heapq.heappop(heap)
        out.append(by_name[n])
        for m in sorted(children[n], key=lambda x: idx[x]):
            indegree[m] -= 1
            if indegree[m] == 0:
                heapq.heappush(heap, (idx[m], m))
    if len(out) != len(primary):
        stuck = sorted(name for name, deg in indegree.items() if deg > 0)
        hint = ", ".join(stuck) if stuck else "unknown"
        msg = f"plugin_hooks.*.runs_after hints form a cycle among hooks: {hint}"
        raise RuntimeError(msg)
    return tuple(out)


def load_plugin_hook_chain(
    workspace: WorkspaceConfig,
    process: ProcessSettings,
) -> PluginHookChain:
    """Load enabled ``sevn.plugin_hooks`` entry points into a sorted chain.
    Args:
        workspace (WorkspaceConfig): Workspace gates (``plugin_hooks.<id>.enabled``).
        process (ProcessSettings): ``SEVN_UNSAFE_PARTIAL_HOOKS`` when imports fail.
    Returns:
        PluginHookChain: Possibly empty when no hooks enabled.
    Raises:
        RuntimeError: Duplicate hook names, invalid names, or policy violations.
        TypeError: Entry point object is not a :class:`~sevn.plugins.hook.PluginHook`.
    Examples:
        >>> import inspect
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.config.settings import ProcessSettings
        >>> inspect.isfunction(load_plugin_hook_chain)
        True
        >>> isinstance(load_plugin_hook_chain(WorkspaceConfig.minimal(), ProcessSettings()), object)
        True
    """
    rows: list[RegisteredHook] = []
    eps = importlib.metadata.entry_points().select(group="sevn.plugin_hooks")
    for ep in eps:
        plugin_id = ep.name
        pol = _policy(workspace, plugin_id)
        if not pol.enabled:
            continue
        trust_owner = pol.trust_level == "owner"
        try:
            raw_obj = ep.load()
            hook = _instantiate_hook(raw_obj)
        except Exception as exc:
            if process.unsafe_partial_plugin_hooks:
                logger.warning("skipping hook {}: {}", plugin_id, exc)
                continue
            raise RuntimeError(f"plugin_hooks.{plugin_id} import failed: {exc}") from exc
        if not valid_hook_name(hook.name):
            msg = f"PluginHook.name {hook.name!r} violates namespace rules"
            raise RuntimeError(msg)
        if not trust_owner:
            _validate_default_trust_capabilities(hook, plugin_id)
        try:
            cmds = hook.register_command()
        except Exception as exc:
            raise RuntimeError(f"register_command failed for {plugin_id}: {exc}") from exc
        if cmds:
            if not trust_owner:
                msg = (
                    f"plugin_hooks.{plugin_id}: register_command requires trust_level=owner "
                    f"(dispatch_tool is disallowed for default trust)"
                )
                raise RuntimeError(msg)
            for c in cmds:
                PluginCommandSpec.model_validate(c)
        rows.append(
            RegisteredHook(
                hook=hook,
                plugin_id=plugin_id,
                distribution_name=_distribution_key(ep),
                entry_point_name=ep.name,
                trust_owner=trust_owner,
            ),
        )
    # duplicate hook.name
    seen: set[str] = set()
    for r in rows:
        if r.hook.name in seen:
            msg = f"duplicate PluginHook.name: {r.hook.name!r}"
            raise RuntimeError(msg)
        seen.add(r.hook.name)
    primary = sorted(
        rows,
        key=lambda r: (r.distribution_name, r.entry_point_name, r.hook.name),
    )
    ordered = order_hooks_by_runs_after(primary, workspace)
    return PluginHookChain(ordered)


def collect_plugin_slash_bindings(chain: PluginHookChain) -> tuple[PluginSlashBinding, ...]:
    """Merge non-colliding :meth:`~sevn.plugins.hook.PluginHook.register_command` rows.
    Args:
        chain (PluginHookChain): Loaded hooks (owner-trust only register commands).
    Returns:
        tuple[PluginSlashBinding, ...]: Slash registry for :class:`CommandDispatcher`.
    Raises:
        RuntimeError: Overlapping ``pattern`` values.
    Examples:
        >>> from sevn.plugins.runner import PluginHookChain
        >>> collect_plugin_slash_bindings(PluginHookChain(()))
        ()
    """
    bindings: list[PluginSlashBinding] = []
    patterns: set[str] = set()
    for rh in chain.hooks:
        for raw in rh.hook.register_command():
            spec = PluginCommandSpec.model_validate(raw)
            if spec.pattern in patterns:
                msg = f"duplicate plugin command pattern {spec.pattern!r}"
                raise RuntimeError(msg)
            patterns.add(spec.pattern)
            bindings.append(
                PluginSlashBinding(
                    command=spec,
                    hook=rh.hook,
                    trust_owner=rh.trust_owner,
                ),
            )
    return tuple(bindings)


@dataclass(frozen=True)
class ChannelPluginSpec:
    """Imported adapter class (subclass of :class:`sevn.gateway.channel_router.ChannelAdapter`)."""

    entry_name: str
    adapter_cls: type[Any]


@dataclass(frozen=True)
class DashboardBadgeEntry:
    """Stub registry row for one ``sevn.dashboard_badges`` entry point (v1)."""

    badge_id: str
    registered: bool
    enabled: bool
    blocked_reason: str | None = None


def _dashboard_badge_enabled(workspace: WorkspaceConfig, badge_id: str) -> bool:
    """Return workspace gate for one dashboard badge id.
    Args:
        workspace (WorkspaceConfig): Parsed workspace document.
        badge_id (str): Entry-point name / badge id.
    Returns:
        bool: ``True`` when ``dashboard.badges.<id>.enabled`` is truthy.
    Examples:
        >>> _dashboard_badge_enabled(WorkspaceConfig.minimal(), "acme.status")
        False
    """
    dash = workspace.dashboard
    if dash is None:
        return False
    raw = dash.model_dump(mode="python")
    badges = raw.get("badges")
    if not isinstance(badges, dict):
        return False
    entry = badges.get(badge_id)
    if isinstance(entry, dict):
        return bool(entry.get("enabled"))
    return False


def load_dashboard_badge_entries(workspace: WorkspaceConfig) -> tuple[DashboardBadgeEntry, ...]:
    """Enumerate ``sevn.dashboard_badges`` entry points without rendering (v1 stub).
    Mission Control badge rendering is deferred to ``specs/24-dashboard.md`` Phase 2;
    v1 only surfaces registry rows for ``sevn doctor --check-extensions``.
    Args:
        workspace (WorkspaceConfig): Workspace gates (``dashboard.badges.<id>.enabled``).
    Returns:
        tuple[DashboardBadgeEntry, ...]: Sorted badge registry rows.
    Examples:
        >>> load_dashboard_badge_entries(WorkspaceConfig.minimal())
        ()
    """
    out: list[DashboardBadgeEntry] = []
    eps = importlib.metadata.entry_points().select(group="sevn.dashboard_badges")
    for ep in sorted(eps, key=lambda item: item.name):
        badge_id = ep.name
        enabled = _dashboard_badge_enabled(workspace, badge_id)
        try:
            ep.load()
            out.append(
                DashboardBadgeEntry(
                    badge_id=badge_id,
                    registered=True,
                    enabled=enabled,
                    blocked_reason=None if enabled else "explicit_flag",
                ),
            )
        except Exception as exc:
            out.append(
                DashboardBadgeEntry(
                    badge_id=badge_id,
                    registered=False,
                    enabled=False,
                    blocked_reason=str(exc),
                ),
            )
    return tuple(out)


def load_channel_plugin_classes(workspace: WorkspaceConfig) -> tuple[ChannelPluginSpec, ...]:
    """Import ``sevn.channels`` entry points that pass the workspace enabled gate.
    Args:
        workspace (WorkspaceConfig): ``channels.<name>.enabled`` flags.
    Returns:
        tuple[ChannelPluginSpec, ...]: Classes for doctor / optional registration.
    Examples:
        >>> load_channel_plugin_classes(WorkspaceConfig.minimal())
        ()
    """
    out: list[ChannelPluginSpec] = []
    ch = workspace.channels
    dumped: dict[str, Any] = {}
    if ch is not None:
        dumped = ch.model_dump(mode="python")
    eps = importlib.metadata.entry_points().select(group="sevn.channels")
    for ep in eps:
        name = ep.name
        blob = dumped.get(name)
        enabled = isinstance(blob, dict) and bool(blob.get("enabled"))
        if not enabled:
            continue
        try:
            cls = ep.load()
            if not isinstance(cls, type):
                msg = f"sevn.channels.{name} must load a class"
                raise TypeError(msg)
            out.append(ChannelPluginSpec(entry_name=name, adapter_cls=cls))
        except Exception as exc:
            logger.warning("channel plugin {} failed load: {}", name, exc)
    return tuple(out)


def build_trigger_mux(chain: PluginHookChain) -> TriggerPluginHooksMux:
    """Construct the multiplex trigger surface used by :mod:`sevn.triggers.dispatcher`.
    Args:
        chain (PluginHookChain): Same ordered hooks as tool interceptors.
    Returns:
        TriggerPluginHooksMux: Forwarder implementing ``TriggerPluginHookSurface``.
    Examples:
        >>> from sevn.plugins.trigger_mux import TriggerPluginHooksMux
        >>> from sevn.plugins.runner import PluginHookChain
        >>> isinstance(build_trigger_mux(PluginHookChain(())), TriggerPluginHooksMux)
        True
    """
    return TriggerPluginHooksMux(chain)


__all__ = [
    "ChannelPluginSpec",
    "DashboardBadgeEntry",
    "build_trigger_mux",
    "collect_plugin_slash_bindings",
    "load_channel_plugin_classes",
    "load_dashboard_badge_entries",
    "load_plugin_hook_chain",
    "order_hooks_by_runs_after",
    "valid_hook_name",
]
