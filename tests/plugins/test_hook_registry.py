"""Unit tests for plugin hook registry (`specs/34-plugin-hooks.md` §10.4)."""

from __future__ import annotations

import importlib.metadata

import pytest

from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import parse_workspace_config
from sevn.plugins.command_spec import PluginCommandSpec
from sevn.plugins.hook import Block, Continue, HookContext, PluginHookBase, Replace
from sevn.plugins.registry import (
    collect_plugin_slash_bindings,
    load_plugin_hook_chain,
    valid_hook_name,
)
from sevn.plugins.runner import PluginHookChain, RegisteredHook


def test_valid_hook_name() -> None:
    """Namespace gate accepts dotted third-party stems."""
    assert valid_hook_name("acme.widget.main")
    assert not valid_hook_name("__core__.bad")
    assert not valid_hook_name("nodot")


def test_runs_after_topo_reorders() -> None:
    """``runs_after`` forces predecessor before dependent."""

    class H1(PluginHookBase):
        pass

    class H2(PluginHookBase):
        pass

    h1 = H1("zeta.first")
    h2 = H2("zeta.second")
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "plugin_hooks": {
                "p1": {"enabled": True, "runs_after": []},
                "p2": {"enabled": True, "runs_after": ["zeta.first"]},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    primary = [
        RegisteredHook(
            hook=h2, plugin_id="p2", distribution_name="d", entry_point_name="p2", trust_owner=False
        ),
        RegisteredHook(
            hook=h1, plugin_id="p1", distribution_name="d", entry_point_name="p1", trust_owner=False
        ),
    ]
    primary.sort(key=lambda r: (r.distribution_name, r.entry_point_name, r.hook.name))
    from sevn.plugins.registry import order_hooks_by_runs_after

    ordered = order_hooks_by_runs_after(list(primary), ws)
    names = [r.hook.name for r in ordered]
    assert names.index("zeta.first") < names.index("zeta.second")


def test_runs_after_cycle_errors() -> None:
    """Cycles in ``runs_after`` fail closed with hook names in the error."""

    class Ha(PluginHookBase):
        pass

    class Hb(PluginHookBase):
        pass

    a = Ha("aa.loopa")
    b = Hb("bb.loopb")
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "plugin_hooks": {
                "pa": {"enabled": True, "runs_after": ["bb.loopb"]},
                "pb": {"enabled": True, "runs_after": ["aa.loopa"]},
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    rows = [
        RegisteredHook(
            hook=a, plugin_id="pa", distribution_name="d", entry_point_name="pa", trust_owner=False
        ),
        RegisteredHook(
            hook=b, plugin_id="pb", distribution_name="d", entry_point_name="pb", trust_owner=False
        ),
    ]
    rows.sort(key=lambda r: (r.distribution_name, r.entry_point_name, r.hook.name))
    from sevn.plugins.registry import order_hooks_by_runs_after

    with pytest.raises(RuntimeError, match=r"cycle among hooks: aa\.loopa, bb\.loopb"):
        order_hooks_by_runs_after(rows, ws)


@pytest.mark.asyncio
async def test_pre_tool_call_block_short_circuits() -> None:
    """First Block stops the chain."""

    class Blocker(PluginHookBase):
        async def pre_tool_call(self, tool_name, args, ctx, /):  # type: ignore[override]
            _ = ctx
            if tool_name == "t1":
                return Block("no")
            return Continue()

    class Later(PluginHookBase):
        def __init__(self) -> None:
            super().__init__("zeta.later")
            self.called = False

        async def pre_tool_call(self, tool_name, args, ctx, /):  # type: ignore[override]
            _ = (tool_name, args, ctx)
            self.called = True
            return Continue()

    b = Blocker("zeta.blocker")
    late = Later()
    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=b,
                plugin_id="p1",
                distribution_name="d",
                entry_point_name="e1",
                trust_owner=True,
            ),
            RegisteredHook(
                hook=late,
                plugin_id="p2",
                distribution_name="d",
                entry_point_name="e2",
                trust_owner=True,
            ),
        ),
    )
    args: dict[str, object] = {"x": 1}
    ctx = HookContext(
        workspace_id="w",
        session_id="s",
        turn_id="t",
        tier="B",
        correlation_id="c",
    )
    out = await chain.run_pre_tool_call("t1", args, ctx, None)
    assert isinstance(out, Block)
    assert late.called is False


@pytest.mark.asyncio
async def test_replace_composes_args() -> None:
    """Replace mutates arg dict for subsequent hooks."""

    class R1(PluginHookBase):
        async def pre_tool_call(self, tool_name, args, ctx, /):  # type: ignore[override]
            _ = (tool_name, ctx)
            return Replace({"a": 2})

    class R2(PluginHookBase):
        async def pre_tool_call(self, tool_name, args, ctx, /):  # type: ignore[override]
            _ = (tool_name, ctx)
            if args.get("a") == 2:
                return Replace({"a": 3})
            return Continue()

    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=R1("zeta.r1"),
                plugin_id="p1",
                distribution_name="d",
                entry_point_name="e1",
                trust_owner=True,
            ),
            RegisteredHook(
                hook=R2("zeta.r2"),
                plugin_id="p2",
                distribution_name="d",
                entry_point_name="e2",
                trust_owner=True,
            ),
        ),
    )
    args: dict[str, object] = {"a": 1}
    ctx = HookContext("w", "s", "t", "B", "c")
    res = await chain.run_pre_tool_call("tool", args, ctx, None)
    assert isinstance(res, Replace)
    assert args["a"] == 3


def test_collect_plugin_slash_collisions() -> None:
    """Duplicate patterns are fatal."""

    class CmdHook(PluginHookBase):
        def register_command(self) -> list[object]:  # type: ignore[override]
            return [
                PluginCommandSpec(pattern="/corp.demo/a", dispatch_key="a"),
                PluginCommandSpec(pattern="/corp.demo/a", dispatch_key="b"),
            ]

    h = CmdHook("corp.x")
    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=h, plugin_id="p", distribution_name="d", entry_point_name="e", trust_owner=True
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="duplicate"):
        collect_plugin_slash_bindings(chain)


class _FakeEP:
    def __init__(self, name: str, hook_factory: object) -> None:
        self.name = name
        self._hook_factory = hook_factory

    def load(self) -> object:
        return self._hook_factory

    @property
    def dist(self) -> None:
        return None


@pytest.mark.asyncio
async def test_transform_terminal_chunk_pipeline() -> None:
    """Terminal interceptors run in registration order."""

    class Bang(PluginHookBase):
        async def transform_terminal_output(self, chunk: str, ctx: HookContext) -> str:  # type: ignore[override]
            _ = ctx
            return chunk + "!"

    chain = PluginHookChain(
        (
            RegisteredHook(
                hook=Bang("z.b"),
                plugin_id="p",
                distribution_name="d",
                entry_point_name="e",
                trust_owner=False,
            ),
        ),
    )
    ctx = HookContext("w", "s", "t", "B", "c")
    out = await chain.transform_terminal_chunk("hi", ctx, None)
    assert out == "hi!"


def test_default_trust_rejects_register_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-owner trust cannot ship slash commands."""

    class CmdHook(PluginHookBase):
        def register_command(self) -> list[object]:  # type: ignore[override]
            return [PluginCommandSpec(pattern="/corp.demo/z", dispatch_key="z")]

    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "plugin_hooks": {"demo": {"enabled": True, "trust_level": "default"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    hook = CmdHook("corp.z")
    fake_ep = _FakeEP("demo", lambda: hook)

    def _stub_eps() -> object:
        class _G:
            def select(self, *, group: str) -> list[_FakeEP]:
                return [fake_ep] if group == "sevn.plugin_hooks" else []

        return _G()

    monkeypatch.setattr(importlib.metadata, "entry_points", _stub_eps)
    with pytest.raises(RuntimeError, match="trust_level=owner"):
        load_plugin_hook_chain(ws, ProcessSettings())


def test_default_trust_rejects_pre_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default trust fail-fast when ``pre_tool_call`` is implemented."""

    class PreHook(PluginHookBase):
        async def pre_tool_call(self, tool_name, args, ctx, /):  # type: ignore[override]
            _ = (tool_name, args, ctx)
            return Continue()

    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "plugin_hooks": {"demo": {"enabled": True, "trust_level": "default"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    hook = PreHook("corp.pre")
    fake_ep = _FakeEP("demo", lambda: hook)

    def _stub_eps() -> object:
        class _G:
            def select(self, *, group: str) -> list[_FakeEP]:
                return [fake_ep] if group == "sevn.plugin_hooks" else []

        return _G()

    monkeypatch.setattr(importlib.metadata, "entry_points", _stub_eps)
    with pytest.raises(RuntimeError, match="pre_tool_call requires trust_level=owner"):
        load_plugin_hook_chain(ws, ProcessSettings())


def test_load_dashboard_badge_entries_empty() -> None:
    """No ``sevn.dashboard_badges`` entry points yields empty stub registry."""
    from sevn.plugins.registry import load_dashboard_badge_entries

    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    assert load_dashboard_badge_entries(ws) == ()
