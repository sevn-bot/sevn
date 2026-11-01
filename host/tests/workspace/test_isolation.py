"""Per-agent scratch dirs, shared locks, and git worktrees."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home
from support.chat import fetch_all


async def _pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    return bot, agent


def _title(home: Path, agent_id: str, title: str) -> None:
    with sqlite3.connect(home / "sevn.db") as connection:
        connection.execute("UPDATE agents SET title = ? WHERE id = ?", (title, agent_id))
        connection.commit()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Sevn Test",
        "GIT_AUTHOR_EMAIL": "sevn-test@example.com",
        "GIT_COMMITTER_NAME": "Sevn Test",
        "GIT_COMMITTER_EMAIL": "sevn-test@example.com",
    }
    return subprocess.run(  # noqa: S603 — fixed git argv, test repo only
        ["git", *args],  # noqa: S607 — git from PATH, like a developer shell
        cwd=repo,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )


async def test_each_agent_has_scratch_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.agents import AgentService

    bot, _agent = await _pair(tmp_path, monkeypatch)
    second = await AgentService().spawn(bot.id)
    scratch = Path(str(bot.workspace_path)) / "tasks" / second.id
    assert scratch.is_dir()


async def test_shared_path_write_takes_lock_and_second_agent_gets_path_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.errors import DomainError
    from sevn.tools.files import write_file

    bot, holder = await _pair(tmp_path, monkeypatch)
    other = await AgentService().spawn(bot.id)
    _title(tmp_path, holder.id, "Invoice fix")
    shared = Path(os.environ["SEVN_WORKSPACES"]).parent / "Shared" / "board.txt"
    await write_file(bot.id, holder.id, str(shared), "one")
    assert shared.read_text(encoding="utf-8") == "one"
    with pytest.raises(DomainError) as exc:
        await write_file(bot.id, other.id, str(shared), "two")
    assert exc.value.code == "path_locked"
    assert "locked" in exc.value.message
    assert exc.value.data["holder_agent_id"] == holder.id
    assert exc.value.data["holder_title"] == "Invoice fix"
    assert shared.read_text(encoding="utf-8") == "one"


async def test_lock_released_on_turn_end_and_expired_after_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.workspace import release_turn
    from sevn.tools.files import write_file

    bot, holder = await _pair(tmp_path, monkeypatch)
    other = await AgentService().spawn(bot.id)
    shared = Path(os.environ["SEVN_WORKSPACES"]).parent / "Shared" / "board.txt"
    await write_file(bot.id, holder.id, str(shared), "held")
    rows = fetch_all(
        tmp_path,
        "SELECT acquired_at, expires_at FROM agent_locks WHERE agent_id = ?",
        (holder.id,),
    )
    assert rows
    acquired = datetime.fromisoformat(str(rows[0]["acquired_at"]))
    expires = datetime.fromisoformat(str(rows[0]["expires_at"]))
    assert timedelta(minutes=9) <= (expires - acquired) <= timedelta(minutes=11)
    await release_turn(holder.id)
    await write_file(bot.id, other.id, str(shared), "released")
    assert shared.read_text(encoding="utf-8") == "released"

    await release_turn(other.id)
    await write_file(bot.id, holder.id, str(shared), "again")
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute(
            "UPDATE agent_locks SET expires_at = ? WHERE agent_id = ?",
            (past, holder.id),
        )
        connection.commit()
    await write_file(bot.id, other.id, str(shared), "expired")
    assert shared.read_text(encoding="utf-8") == "expired"


async def test_own_scratch_dir_needs_no_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.tools.files import read_file, write_file

    bot, first = await _pair(tmp_path, monkeypatch)
    second = await AgentService().spawn(bot.id)
    await write_file(bot.id, first.id, f"tasks/{first.id}/a.txt", "alpha")
    await write_file(bot.id, second.id, f"tasks/{second.id}/b.txt", "beta")
    assert await read_file(bot.id, first.id, f"tasks/{first.id}/a.txt") == "alpha"
    assert await read_file(bot.id, second.id, f"tasks/{second.id}/b.txt") == "beta"


async def test_worktree_isolation_in_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.workspace import ensure
    from sevn.tools.files import write_file

    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    (repo / "README").write_text("base\n", encoding="utf-8")
    assert _git(repo, "add", "README").returncode == 0
    assert _git(repo, "commit", "-m", "init").returncode == 0
    bot, agent = await _pair(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute(
            "UPDATE bots SET workspace_path = ? WHERE id = ?",
            (str(repo), bot.id),
        )
        connection.execute(
            "UPDATE agents SET isolation = 'worktree' WHERE id = ?",
            (agent.id,),
        )
        connection.commit()
    note = await ensure(agent.id)
    assert note == ""
    await write_file(bot.id, agent.id, "f.txt", "from-agent")
    assert not (repo / "f.txt").exists()
    worktree = tmp_path / "worktrees" / agent.id / "f.txt"
    assert worktree.read_text(encoding="utf-8") == "from-agent"
    branch = _git(repo, "rev-parse", "--verify", f"sevn/{agent.id}")
    assert branch.returncode == 0, branch.stderr
    status = _git(repo, "status", "--porcelain")
    assert status.returncode == 0, status.stderr
    assert "f.txt" not in status.stdout


async def test_worktree_isolation_ignored_outside_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.workspace import ensure

    bot, agent = await _pair(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute(
            "UPDATE agents SET isolation = 'worktree' WHERE id = ?",
            (agent.id,),
        )
        connection.commit()
    note = await ensure(agent.id)
    assert note == "worktree ignored: workspace is not a git repo"
    scratch = Path(str(bot.workspace_path)) / "tasks" / agent.id
    assert scratch.is_dir()
    assert not (tmp_path / "worktrees" / agent.id).exists()


def _ran_filters(marker: Path) -> list[str]:
    return [
        str(path) for path in (marker, Path(f"{marker}-2"), Path(f"{marker}-3")) if path.exists()
    ]


async def test_worktree_checkout_runs_no_bot_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bot can write .git/config and .git/info/attributes. A smudge or
    process filter there must not run on the host when the worktree is made."""
    from sevn.domain.workspace import ensure

    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    (repo / "README").write_text("base\n", encoding="utf-8")
    (repo / "notes.txt").write_text("notes\n", encoding="utf-8")
    assert _git(repo, "add", "README", "notes.txt").returncode == 0
    assert _git(repo, "commit", "-m", "init").returncode == 0
    marker = tmp_path / "filter-ran"
    with (repo / ".git" / "config").open("a", encoding="utf-8") as config:
        config.write(
            f'[filter "evil"]\n\tsmudge = touch {marker} && cat\n\trequired = true\n'
            f'[filter "a=b.c"]\n\tsmudge = touch {marker}-2 && cat\n'
            f"\tprocess = touch {marker}-3\n"
        )
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text(
        "README filter=evil\nnotes.txt filter=a=b.c\n", encoding="utf-8"
    )
    bot, agent = await _pair(tmp_path, monkeypatch)
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute(
            "UPDATE bots SET workspace_path = ? WHERE id = ?",
            (str(repo), bot.id),
        )
        connection.execute(
            "UPDATE agents SET isolation = 'worktree' WHERE id = ?",
            (agent.id,),
        )
        connection.commit()
    note = await ensure(agent.id)
    assert note == ""
    assert _ran_filters(marker) == []
    worktree = tmp_path / "worktrees" / agent.id
    assert (worktree / "README").read_text(encoding="utf-8") == "base\n"
    assert (worktree / "notes.txt").read_text(encoding="utf-8") == "notes\n"


@pytest.mark.parametrize("purge", [False, True])
async def test_bot_delete_cleans_only_its_worktrees_when_purged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purge: bool
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.domain.workspace import ensure

    bot, agent = await _pair(tmp_path, monkeypatch)
    repo = Path(str(bot.workspace_path))
    assert _git(repo, "init", "-b", "main").returncode == 0
    (repo / "README").write_text("base", encoding="utf-8")
    assert _git(repo, "add", "README").returncode == 0
    assert _git(repo, "commit", "-m", "init").returncode == 0
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute("UPDATE agents SET isolation='worktree' WHERE id=?", (agent.id,))
    assert await ensure(agent.id) == ""
    checkout = tmp_path / "worktrees" / agent.id
    (checkout / "uncommitted.txt").write_text("bot data", encoding="utf-8")
    other_bot = await BotService().create("Other")
    other_agent = await AgentService().spawn(other_bot.id)
    other_checkout = tmp_path / "worktrees" / other_agent.id
    other_checkout.mkdir()
    (other_checkout / "keep.txt").write_text("other bot data", encoding="utf-8")
    await BotService().delete(bot.id, purge=purge)
    assert await asyncio.to_thread(checkout.exists) is not purge
    assert await asyncio.to_thread(repo.exists) is not purge
    assert (other_checkout / "keep.txt").read_text(encoding="utf-8") == "other bot data"
    if not purge:
        assert (checkout / "uncommitted.txt").read_text(encoding="utf-8") == "bot data"


async def test_new_filter_after_config_read_is_confined(tmp_path: Path, monkeypatch) -> None:
    from sevn.domain import workspace

    bot, agent = await _pair(tmp_path, monkeypatch)
    repo = Path(bot.workspace_path)
    assert _git(repo, "init", "-b", "main").returncode == 0
    (repo / "notes.txt").write_text("notes\n")
    (repo / ".gitattributes").write_text("notes.txt filter=late\n")
    assert _git(repo, "add", ".").returncode == 0
    assert _git(repo, "commit", "-m", "init").returncode == 0
    marker = tmp_path / "outside-checkout"
    original = workspace._filter_drivers

    async def change_config(git, cwd, env):
        names = await original(git, cwd, env)
        with (repo / ".git" / "config").open("a") as config:
            config.write(f'[filter "late"]\n\tsmudge = touch {marker}; cat\n')
        return names

    monkeypatch.setattr(workspace, "_filter_drivers", change_config)
    with sqlite3.connect(tmp_path / "sevn.db") as connection:
        connection.execute("UPDATE agents SET isolation='worktree' WHERE id=?", (agent.id,))
    assert await workspace.ensure(agent.id) == ""
    assert not marker.exists()
    assert (tmp_path / "worktrees" / agent.id / "notes.txt").read_text() == "notes\n"
