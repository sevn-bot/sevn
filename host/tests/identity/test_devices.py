"""Paired devices, revocation, the identity package and the 0011 migration (plan 0055 D2, K-MIG).

Contracts pinned here (see ``.ignorelocal/test-plans/0055-direct-multi-host.md``):
- ``devices.list`` (owner) -> ``{"devices": [DeviceRecord]}``; ``devices.rename(id, name, op_id)``
  and ``devices.revoke(id, op_id)`` (owner, mutating) -> ``DeviceRecord``.
- ``DeviceRecord``: ``id, name, platform, scope, created_at, last_seen, revoked_at`` (at least).
- Remote revoke of the last live owner device -> ``last_owner``; unknown id -> ``not_found``.
- ``sevn devices list --json`` / ``sevn devices revoke <id>`` work with no host running.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sqlite3
import subprocess
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from support.memory import MemoryHost, memory_host
from support.migrations import down_revision_of, revision_ending, script_head
from support.pairing import call, op_id, owner_client, pair_device, register_methods
from support.repo import repo_root

LAST_OWNER = "cannot revoke the last owner device"
DEVICE_COLUMNS = {
    "id",
    "name",
    "platform",
    "pubkey_ed25519",
    "pubkey_x25519",
    "scope",
    "created_at",
    "last_seen",
    "revoked_at",
}
# K-MIG: this plan's revision is the one ending in "_devices" (planned 0011_devices); its
# parent is whatever head it was chained onto, so a re-chain at merge keeps these green.
DEVICES_SUFFIX = "_devices"


@asynccontextmanager
async def _host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[MemoryHost]:
    async with memory_host(tmp_path, monkeypatch) as host:
        register_methods()
        yield host


async def _dispatch(session: Any, method: str, params: dict[str, Any]) -> Any:
    from sevn.contracts.frames import Req
    from sevn.protocol.registry import dispatch

    return await dispatch(session, Req(t="req", id="1", m=method, p=params))


def _remote(host: MemoryHost, *, scope: str, device_id: str) -> Any:
    from sevn.protocol.session import Session

    return Session.for_test(  # type: ignore[call-arg]
        scope=scope, loopback=False, hub=host.hub, device_id=device_id
    )


# --- devices.* -------------------------------------------------------------------------------


async def test_list_and_rename_are_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        phone = await pair_device(host, owner, scope="member", name="Phone")
        listed = await call(owner, "devices.list", {})
        assert [row["id"] for row in listed["r"]["devices"]] == [phone.id]
        renamed = await call(
            owner, "devices.rename", {"id": phone.id, "name": "Work phone", "op_id": op_id()}
        )
        assert renamed["r"]["id"] == phone.id
        assert renamed["r"]["name"] == "Work phone"
        again = await call(owner, "devices.list", {})
        assert again["r"]["devices"][0]["name"] == "Work phone"
        for scope in ("member", "read_only"):
            session = _remote(host, scope=scope, device_id=phone.id)
            for method, params in (
                ("devices.list", {}),
                ("devices.rename", {"id": phone.id, "name": "x", "op_id": op_id()}),
                ("devices.revoke", {"id": phone.id, "op_id": op_id()}),
            ):
                res = await _dispatch(session, method, params)
                assert res.e is not None, (scope, method)
                assert res.e.code == "forbidden", (scope, method)


async def test_revoke_unknown_device_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        res = await call(owner, "devices.revoke", {"id": "dev_missing", "op_id": op_id()})
        assert res["e"]["code"] == "not_found"


def test_revoke_persists_and_cli_revoke_works_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    paired: dict[str, str] = {}

    async def seed(host: MemoryHost) -> None:
        owner = await owner_client(host)
        phone = await pair_device(host, owner, scope="member", name="Phone")
        tablet = await pair_device(host, owner, scope="read_only", name="Tablet")
        paired["phone"], paired["tablet"] = phone.id, tablet.id
        revoked = await call(owner, "devices.revoke", {"id": phone.id, "op_id": op_id()})
        assert revoked["r"]["id"] == phone.id
        assert revoked["r"]["revoked_at"] is not None

    asyncio.run(_with_host(tmp_path, monkeypatch, seed))

    # No host is running now: the CLI reads and writes the store directly.
    from sevn.cli import app

    runner = CliRunner()
    revoke = runner.invoke(app, ["devices", "revoke", paired["tablet"], "--home", str(tmp_path)])
    assert revoke.exit_code == 0, revoke.output
    assert paired["tablet"] in revoke.output
    listed = runner.invoke(app, ["devices", "list", "--json", "--home", str(tmp_path)])
    assert listed.exit_code == 0, listed.output
    rows = {row["id"]: row for row in json.loads(listed.output)}
    assert set(rows) == {paired["phone"], paired["tablet"]}
    assert rows[paired["phone"]]["revoked_at"] is not None
    assert rows[paired["tablet"]]["revoked_at"] is not None
    assert rows[paired["tablet"]]["name"] == "Tablet"

    async def check(host: MemoryHost) -> None:
        owner = await owner_client(host)
        after = await call(owner, "devices.list", {})
        states = {row["id"]: row["revoked_at"] for row in after["r"]["devices"]}
        assert all(value is not None for value in states.values()), states

    asyncio.run(_with_host(tmp_path, monkeypatch, check))


def test_cli_revoke_unknown_device_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    asyncio.run(_with_host(tmp_path, monkeypatch, _noop))
    from sevn.cli import app

    result = CliRunner().invoke(app, ["devices", "revoke", "dev_missing", "--home", str(tmp_path)])
    assert result.exit_code == 1
    assert "device not found: dev_missing" in result.output + (result.stderr or "")


async def test_last_owner_not_revocable_remotely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        owner = await owner_client(host)
        first = await pair_device(host, owner, scope="owner", name="Laptop")
        second = await pair_device(host, owner, scope="owner", name="Phone")
        remote = _remote(host, scope="owner", device_id=first.id)
        # Two live owners: a remote owner may revoke one of them.
        ok = await _dispatch(remote, "devices.revoke", {"id": second.id, "op_id": op_id()})
        assert ok.e is None, ok.e
        # Now `first` is the last live owner device: refused from a remote session.
        refused = await _dispatch(remote, "devices.revoke", {"id": first.id, "op_id": op_id()})
        assert refused.e is not None
        assert refused.e.code == "last_owner"
        assert refused.e.message == LAST_OWNER
        listed = await call(owner, "devices.list", {})
        live = {row["id"] for row in listed["r"]["devices"] if row["revoked_at"] is None}
        assert live == {first.id}
        # The loopback owner session can still revoke it (recovery stays local).
        local = await call(owner, "devices.revoke", {"id": first.id, "op_id": op_id()})
        assert local["r"]["revoked_at"] is not None


# --- identity package ------------------------------------------------------------------------


def test_identity_imports_unchanged() -> None:
    """0001's ``sevn.identity`` names still import after the move into a package."""
    import sevn.identity as identity
    from sevn.identity import HostIdentity, SecretStore, load_or_create

    assert hasattr(identity, "__path__"), "sevn.identity must be a package"
    keys = importlib.import_module("sevn.identity.keys")
    assert keys.load_or_create is load_or_create
    assert keys.HostIdentity is HostIdentity
    assert keys.SecretStore is SecretStore
    for name in ("pairing", "devices", "handshake"):
        importlib.import_module(f"sevn.identity.{name}")


def test_identity_still_loads_the_same_host_key() -> None:
    """Regression guard for the W2 move: green today, must stay green."""
    from sevn.identity import load_or_create

    store = _DictStore()
    first = load_or_create(store)
    second = load_or_create(store)
    assert first == second
    assert first.host_id.startswith("host_")
    assert len(first.public_key) == 32


class _DictStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str:
        from sevn.secrets.errors import SecretNotFound

        if name not in self.values:
            raise SecretNotFound(name)
        return self.values[name]

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


# --- K-MIG -----------------------------------------------------------------------------------


def test_migrations_single_head() -> None:
    completed = subprocess.run(
        ["make", "db-heads"],  # noqa: S607
        cwd=repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    head = script_head()
    assert head == revision_ending(DEVICES_SUFFIX)
    assert head in completed.stdout, completed.stdout


def test_migration_file_chains_from_previous_head() -> None:
    versions = repo_root() / "host/src/sevn/store/migrations/versions"
    matches = sorted(versions.glob("*_devices.py"))
    assert len(matches) == 1, matches
    spec = importlib.util.spec_from_file_location("sevn_devices_migration", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == revision_ending(DEVICES_SUFFIX)
    assert module.revision.endswith("_devices")
    assert module.down_revision == down_revision_of(module.revision)
    assert module.down_revision is not None
    text = matches[0].read_text(encoding="utf-8")
    assert "sevn.store.models" not in text, "migrations are frozen DDL"


def test_upgrade_from_previous_head(tmp_path: Path) -> None:
    """A database at 0005 with rows in it upgrades to 0011; the rows survive."""
    from alembic import command
    from sevn.store.db import _alembic_config

    db = tmp_path / "sevn.db"
    cfg = _alembic_config()
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    this_head = revision_ending(DEVICES_SUFFIX)
    command.upgrade(cfg, down_revision_of(this_head))
    stamp = "2026-11-01 09:00:00.000000+00:00"
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO events (seq, type, entity, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (1, "system.ping", "host", '{"note": "before 0011"}', stamp),
        )
        connection.execute(
            "INSERT INTO share_links (id, secret_hash, label, bot_id, created_at, expires_at,"
            " revoked_at, last_opened_at, opens) VALUES (?, ?, ?, NULL, ?, ?, NULL, NULL, 0)",
            ("shr_fixture", "0" * 64, "Fixture link", stamp, stamp),
        )
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        events = connection.execute("SELECT seq, type, payload FROM events").fetchall()
        shares = connection.execute("SELECT id, label FROM share_links").fetchall()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        columns = {row[1] for row in connection.execute("PRAGMA table_info(devices)")}
        nullable = {row[1]: not row[3] for row in connection.execute("PRAGMA table_info(devices)")}
    assert version == [(this_head,)]
    assert events == [(1, "system.ping", '{"note": "before 0011"}')]
    assert shares == [("shr_fixture", "Fixture link")]
    assert {"devices", "pairing_tickets", "pairing_attempts"} <= tables
    assert columns == DEVICE_COLUMNS
    assert nullable["pubkey_x25519"] is True
    assert nullable["revoked_at"] is True
    assert nullable["pubkey_ed25519"] is False
    assert nullable["scope"] is False


async def _noop(_host: MemoryHost) -> None:
    return None


async def _with_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: Callable[[MemoryHost], Any],
) -> None:
    async with _host(tmp_path, monkeypatch) as host:
        await body(host)
