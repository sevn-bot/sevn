"""Workspace file tools, user.ask, and agent tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home
from support.chat import fetch_all, insert_turn, mint_id


async def _pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    return bot, agent


async def test_workspace_path_escape_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.errors import DomainError
    from sevn.tools.files import read_file, write_file

    bot, agent = await _pair(tmp_path, monkeypatch)
    workspace = Path(str(bot.workspace_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("do-not-read", encoding="utf-8")
    link = workspace / "escape"
    link.symlink_to(outside, target_is_directory=True)
    cases = ("../outside/secret.txt", str(secret), "escape/secret.txt")
    for path in cases:
        with pytest.raises(DomainError) as exc:
            await read_file(bot.id, agent.id, path)
        assert exc.value.code == "path_outside_workspace"
        assert "outside" in exc.value.message
        with pytest.raises(DomainError) as write_exc:
            await write_file(bot.id, agent.id, path, "nope")
        assert write_exc.value.code == "path_outside_workspace"
    assert secret.read_text(encoding="utf-8") == "do-not-read"


async def test_write_then_read_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.tools.files import read_file, write_file

    bot, agent = await _pair(tmp_path, monkeypatch)
    await write_file(bot.id, agent.id, "notes/hello.txt", "hello")
    assert await read_file(bot.id, agent.id, "notes/hello.txt") == "hello"
    stored = Path(str(bot.workspace_path)) / "notes" / "hello.txt"
    assert stored.read_text(encoding="utf-8") == "hello"


async def test_edit_file_does_not_persist_injection_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D11 wraps what the model sees. edit_file must not write that wrapper into the file."""
    from fakes.fake_jev import FakeJev
    from sevn.decisions.jev import use_client
    from sevn.tools.files import edit_file, read_file, write_file

    wrapped = '<untrusted_content flagged="injection">{text}</untrusted_content>'
    bot, agent = await _pair(tmp_path, monkeypatch)
    await write_file(bot.id, agent.id, "note.txt", "hello world")
    use_client(FakeJev(answers={"inbound.injection": 0.91}))
    try:
        seen = await read_file(bot.id, agent.id, "note.txt")
        assert seen == wrapped.format(text="hello world")
        await edit_file(bot.id, agent.id, "note.txt", "hello", "goodbye")
        stored = (Path(str(bot.workspace_path)) / "note.txt").read_text(encoding="utf-8")
        assert stored == "goodbye world"
        assert "untrusted_content" not in stored
        seen_after = await read_file(bot.id, agent.id, "note.txt")
        assert seen_after == wrapped.format(text="goodbye world")
    finally:
        use_client(None)


async def test_user_ask_creates_question_pending_and_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.user import ask

    bot, agent = await _pair(tmp_path, monkeypatch)
    _ = bot
    turn_id = await insert_turn(
        tmp_path,
        agent_id=agent.id,
        thread_id=agent.thread_id,
        job_id=mint_id("job_"),
        status="running",
        model_messages=[],
    )
    pending_id = await ask(agent.id, turn_id, "Which day?")
    assert isinstance(pending_id, str) and pending_id != ""
    rows = fetch_all(
        tmp_path,
        "SELECT kind, status, answer, payload FROM pending_requests WHERE id = ?",
        (pending_id,),
    )
    assert rows[0]["kind"] == "question"
    assert rows[0]["status"] == "waiting"
    assert rows[0]["answer"] is None
    assert "Which day?" in str(rows[0]["payload"])
    turns = fetch_all(tmp_path, "SELECT status FROM turns WHERE id = ?", (turn_id,))
    assert turns[0]["status"] == "waiting"


async def test_agent_list_read_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    from sevn.domain.agents import AgentService
    from sevn.tools.agents import close_agent, list_agents, read_agent

    bot, agent = await _pair(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute(
            "UPDATE agents SET title = ?, summary = ? WHERE id = ?",
            ("Invoice fix", "taxes", agent.id),
        )
        connection.commit()
    listed = await list_agents(bot.id)
    assert any(item.id == agent.id for item in listed)
    detail = await read_agent(agent.id)
    assert detail.title == "Invoice fix"
    assert detail.summary == "taxes"
    await close_agent(agent.id)
    closed = await AgentService().get(agent.id)
    assert closed.status == "done"


async def test_eager_and_deferred_split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sevn.memory.tools
    import sevn.tools.agents
    import sevn.tools.files
    import sevn.tools.user
    from sevn.tools.registry import toolsets_for

    bot, _agent = await _pair(tmp_path, monkeypatch)
    assert sevn.memory.tools.__name__ == "sevn.memory.tools"
    assert sevn.tools.agents.__name__ == "sevn.tools.agents"
    assert sevn.tools.files.__name__ == "sevn.tools.files"
    assert sevn.tools.user.__name__ == "sevn.tools.user"
    eager: set[str] = set()
    deferred: set[str] = set()
    for item in toolsets_for(bot):
        eager.update(item.eager)
        deferred.update(item.deferred)
    assert {
        "user.ask",
        "memory.save",
        "memory.search",
        "files.attach",
        "agent.list",
        "agent.read",
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
        "grep",
    } <= eager
    assert {"memory.forget", "memory.pin", "agent.close"} <= deferred
    assert eager.isdisjoint(deferred)
