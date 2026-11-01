"""Bot services, protocol methods, and upgrade from 0001 to head."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from support.chat import (
    assert_prefixed_id,
    connected,
    error_body,
    fetch_all,
    load_modules,
    mint_id,
    ok,
    request,
)
from support.repo import repo_root


def _assert_workspace(body: dict[str, object], bot_id: str) -> None:
    from sevn.paths import Paths

    workspace = Path(str(body["workspace_path"])).resolve()
    assert workspace == (Paths.from_env().workspaces / bot_id).resolve()
    assert (workspace / "tasks").is_dir()


def _tasks_dir(path: Path) -> bool:
    return path.is_dir() and (path / "tasks").is_dir()


def _missing(path: Path) -> bool:
    return not path.exists()


async def _create(client: object, name: str, **extra: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "bots.create",
        {"name": name, "op_id": mint_id("op_"), **extra},
    )
    return ok(frame)


async def test_create_bot_creates_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        backend = open_backend(Settings.load(), Paths.from_env())
        backend.set("provider/anthropic", mint_id("key_"))
        body = await _create(client, "alpha")
        bot_id = assert_prefixed_id(body["id"], "bot_")
        assert body["name"] == "alpha"
        assert body["runtime"] == "pydantic_ai"
        assert body["model"] == "anthropic:claude-sonnet-4-5"
        assert body["access"] == "workspace"
        assert body["approval_policy"] == "ask"
        _assert_workspace(body, bot_id)


def _assert_model_invalid(frame: dict[str, object]) -> None:
    error = error_body(frame)
    assert error["code"] == "invalid_params"
    data = error["data"]
    assert isinstance(data, dict)
    errors = data["errors"]
    assert isinstance(errors, list)
    assert errors[0]["loc"] == ["model"]


async def test_create_rejects_empty_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bots.create with model "" is invalid_params. Other ids stay selectable."""
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame, _earlier = await request(
            client,
            "bots.create",
            {"name": "alpha", "model": "", "op_id": mint_id("op_")},
        )
        _assert_model_invalid(frame)


async def test_update_rejects_empty_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """bots.update with model "" is invalid_params. Other ids stay selectable."""
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        open_backend(Settings.load(), Paths.from_env()).set("provider/anthropic", mint_id("key_"))
        created = await _create(client, "alpha")
        assert created["model"] != ""
        frame, _earlier = await request(
            client,
            "bots.update",
            {"bot_id": created["id"], "model": "", "op_id": mint_id("op_")},
        )
        _assert_model_invalid(frame)


async def test_create_requires_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame, _earlier = await request(client, "bots.create", {"op_id": mint_id("op_")})
        error = error_body(frame)
        assert error["code"] == "invalid_params"
        data = error["data"]
        assert isinstance(data, dict)
        errors = data["errors"]
        assert isinstance(errors, list)
        assert errors[0]["loc"] == ["name"]


async def test_update_null_clears_effort_and_folder_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit null clears effort and folder_id. Omitting those keys leaves them."""
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        created = await _create(client, "alpha", effort="high", folder_id="folder_kept")
        assert created["effort"] == "high"
        assert created["folder_id"] == "folder_kept"
        frame, _earlier = await request(
            client,
            "bots.update",
            {
                "bot_id": created["id"],
                "effort": None,
                "folder_id": None,
                "op_id": mint_id("op_"),
            },
        )
        cleared = ok(frame)
        stored = fetch_all(
            tmp_path,
            "SELECT name, model, runtime, effort, folder_id FROM bots WHERE id = ?",
            (created["id"],),
        )
        row = stored[0]
        assert (
            cleared["name"],
            cleared["model"],
            cleared["runtime"],
            cleared["effort"],
            cleared["folder_id"],
            row["name"],
            row["model"],
            row["runtime"],
            row["effort"],
            row["folder_id"],
        ) == (
            created["name"],
            created["model"],
            created["runtime"],
            None,
            None,
            created["name"],
            created["model"],
            created["runtime"],
            None,
            None,
        )
        frame, _earlier = await request(
            client,
            "bots.update",
            {
                "bot_id": created["id"],
                "effort": "low",
                "folder_id": "folder_again",
                "op_id": mint_id("op_"),
            },
        )
        ok(frame)
        frame, _earlier = await request(
            client,
            "bots.update",
            {"bot_id": created["id"], "title": "Still", "op_id": mint_id("op_")},
        )
        omitted = ok(frame)
        kept = fetch_all(
            tmp_path,
            "SELECT name, model, runtime, effort, folder_id FROM bots WHERE id = ?",
            (created["id"],),
        )[0]
        assert omitted["title"] == "Still"
        assert (
            omitted["name"],
            omitted["model"],
            omitted["runtime"],
            omitted["effort"],
            omitted["folder_id"],
            kept["name"],
            kept["model"],
            kept["runtime"],
            kept["effort"],
            kept["folder_id"],
        ) == (
            created["name"],
            created["model"],
            created["runtime"],
            "low",
            "folder_again",
            created["name"],
            created["model"],
            created["runtime"],
            "low",
            "folder_again",
        )


async def test_update_bot_emits_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (host, client):
        created = await _create(client, "alpha")
        frame, _earlier = await request(
            client,
            "bots.update",
            {"bot_id": created["id"], "title": "Edited", "op_id": mint_id("op_")},
        )
        updated = ok(frame)
        assert updated["title"] == "Edited"
        rows = await host.outbox.since(0)
        events = [row for row in rows if row.type == "bot.updated"]
        assert events
        payload = events[-1].payload
        assert payload["bot_id"] == created["id"]
        assert payload["title"] == "Edited"


async def test_delete_bot_keeps_workspace_unless_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (host, client):
        kept = await _create(client, "kept")
        removed = await _create(client, "removed")
        kept_path = Path(str(kept["workspace_path"]))
        removed_path = Path(str(removed["workspace_path"]))
        frame, _earlier = await request(
            client,
            "bots.delete",
            {"bot_id": kept["id"], "purge": False, "op_id": mint_id("op_")},
        )
        ok(frame)
        assert _tasks_dir(kept_path)
        frame, _earlier = await request(
            client,
            "bots.delete",
            {"bot_id": removed["id"], "purge": True, "op_id": mint_id("op_")},
        )
        ok(frame)
        assert _missing(removed_path)
        rows = await host.outbox.since(0)
        deleted = {row.payload.get("bot_id") for row in rows if row.type == "bot.deleted"}
        assert {kept["id"], removed["id"]} <= deleted


async def test_delete_bot_cascades_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.agents import AgentService

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        created = await _create(client, "parent")
        spawned = await AgentService().spawn(bot_id=str(created["id"]))
        assert_prefixed_id(spawned.id, "agent_")
        frame, _earlier = await request(
            client,
            "bots.delete",
            {"bot_id": created["id"], "purge": False, "op_id": mint_id("op_")},
        )
        ok(frame)
        rows = fetch_all(tmp_path, "SELECT id FROM agents WHERE bot_id = ?", (created["id"],))
        assert rows == []


async def test_list_bots_ordered_by_updated_desc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        empty, _earlier = await request(client, "bots.list", {})
        assert ok(empty)["bots"] == []
        first = await _create(client, "first")
        second = await _create(client, "second")
        frame, _earlier = await request(
            client,
            "bots.update",
            {"bot_id": first["id"], "title": "Fresh", "op_id": mint_id("op_")},
        )
        ok(frame)
        listed, _earlier = await request(client, "bots.list", {})
        ids = [item["id"] for item in ok(listed)["bots"]]
        assert ids == [first["id"], second["id"]]


def test_migrations_single_head() -> None:
    completed = subprocess.run(
        ["make", "--no-print-directory", "db-heads"],  # noqa: S607
        cwd=repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, completed.stdout
    assert "0003_router_memory" in lines[0]
    assert "(head)" in lines[0]


def test_upgrade_from_0001_reaches_0003(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    database = tmp_path / "sevn.db"
    cfg = Config(str(repo_root() / "host/alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(cfg, "0001_initial")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO events (type, entity, payload, created_at) VALUES (?, ?, ?, ?)",
            ("system.ping", "system", '{"note":"kept"}', "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
    command.upgrade(cfg, "head")
    with sqlite3.connect(database) as connection:
        event = connection.execute("SELECT type, payload FROM events").fetchone()
        assert event is not None
        assert event[0] == "system.ping"
        assert "kept" in str(event[1])
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version is not None
    assert str(version[0]) == "0003_router_memory"
    for name in ("bots", "agents", "threads", "turns", "messages", "jobs", "pending_requests"):
        assert name in tables
