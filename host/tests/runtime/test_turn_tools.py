"""The pydantic turn must run the sandboxed shell and a real write (WV F3).

``sevn.tools.core.shell`` returns ``"ok"`` and does not run the command.
``sevn.tools.core.write_file`` returns the path and does not write. The
runtime also does not import ``sevn.tools.shell``, so that toolset is absent
until some other import registers it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home


async def _pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    return bot, agent


def _note(workspace: object) -> str | None:
    matches = list(Path(str(workspace)).rglob("note.txt"))
    if not matches:
        return None
    return matches[0].read_text(encoding="utf-8")


def _file_text(workspace: object, name: str) -> str | None:
    matches = list(Path(str(workspace)).rglob(name))
    if not matches:
        return None
    return matches[0].read_text(encoding="utf-8")


def _restore_shell() -> None:
    import sevn.tools.shell as shell_mod
    from sevn.tools.registry import register_toolset

    register_toolset("shell", shell_mod.shell_toolset, set(), deferred={"shell"})


async def _invoke(fn: object, **kwargs: str) -> object:
    assert callable(fn)
    result = fn(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def test_runtime_import_registers_shell_toolset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the pydantic runtime registers the sandboxed shell toolset."""
    from sevn.runtime.runtimes.pydantic_ai import _register_feature_tools
    from sevn.tools.registry import toolsets_for, unregister_toolset

    bot, _agent = await _pair(tmp_path, monkeypatch)
    unregister_toolset("shell")
    try:
        _register_feature_tools()
        names = {item.name for item in toolsets_for(bot)}
        assert "shell" in names, f"registered toolsets: {sorted(names)}"
    finally:
        _restore_shell()


async def test_pydantic_turn_shell_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The shell tool wired onto a pydantic turn runs the command."""
    from sevn.runtime.runtimes.pydantic_ai import _tools
    from sevn.tools.core import shell as core_shell

    bot, agent = await _pair(tmp_path, monkeypatch)
    tools = _tools(bot, agent_id=agent.id, turn_id="turn_wv_f3")
    shell_tools = [tool for tool in tools if str(getattr(tool, "name", "")) == "shell"]
    assert shell_tools, tools
    for tool in shell_tools:
        await _invoke(getattr(tool, "function", None), command="printf hi > note.txt")
        wrote = _note(bot.workspace_path)
        assert wrote == "hi", (
            f"shell tool left {wrote!r}; core.shell returns ok and does not enter the sandbox"
        )
        assert getattr(tool, "function", None) is not core_shell


async def test_pydantic_turn_write_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write tool wired onto a pydantic turn persists the file."""
    from sevn.runtime.runtimes.pydantic_ai import _tools
    from sevn.tools.core import write_file as core_write

    bot, agent = await _pair(tmp_path, monkeypatch)
    tools = _tools(bot, agent_id=agent.id, turn_id="turn_wv_f3")
    write_tools = [
        tool for tool in tools if str(getattr(tool, "name", "")) in {"write", "write_file"}
    ]
    assert write_tools, tools
    for index, tool in enumerate(write_tools):
        name = f"written-{index}.txt"
        await _invoke(getattr(tool, "function", None), path=name, content="stored")
        text = _file_text(bot.workspace_path, name)
        assert text == "stored", f"{name} left {text!r}; core write does not write"
        assert getattr(tool, "function", None) is not core_write
