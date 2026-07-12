"""Mission Control sub-agents API tests (W6.4)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.agent.subagents.models import SubAgentLimitExceeded
from sevn.agent.subagents.supervisor import SubAgentSpec, SubAgentSupervisor
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


def _workspace_cfg() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=False,
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def _sqlite_factory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _build_app(tmp_path: Path):
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = _workspace_cfg()
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=_sqlite_factory)
    return app, cfg, layout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    app, _cfg, _layout = _build_app(tmp_path)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    return _csrf_headers(client)


async def _spawn_long_l1(supervisor: SubAgentSupervisor, *, task_summary: str = "slow task") -> str:
    async def _work() -> None:
        await asyncio.sleep(120)

    handle = await supervisor.spawn(
        SubAgentSpec(
            level=1,
            role="tier_b",
            body=_work,
            session_id="s-mc",
            channel="telegram",
            task_summary=task_summary,
        ),
    )
    assert not isinstance(handle, SubAgentLimitExceeded)
    await asyncio.sleep(0.05)
    return handle.id


def _spawn_long_l1_on_client(client: TestClient, *, task_summary: str = "slow task") -> str:
    supervisor: SubAgentSupervisor = client.app.state.subagent_supervisor

    async def _spawn() -> str:
        return await _spawn_long_l1(supervisor, task_summary=task_summary)

    return client.portal.call(_spawn)


def test_mission_subagents_get_requires_owner_auth(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get("/api/v1/mission/subagents")
        assert resp.status_code == 401


def test_mission_subagents_get_shape(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/mission/subagents")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {"counts", "running", "recent", "limits", "telemetry"}
        assert body["counts"]["level1_total"] == 0
        assert body["limits"]["by_role"]["tier_b"]["max_level1"] == 5
        assert body["limits"]["config_edit_path"] == "/mission/config"


def test_mission_subagents_kill_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        run_id = _spawn_long_l1_on_client(client)

        listed = client.get("/api/v1/mission/subagents")
        assert listed.status_code == 200
        running = listed.json()["running"]
        assert any(row["id"] == run_id for row in running)

        kill = client.post(f"/api/v1/mission/subagents/{run_id}/kill", headers=headers)
        assert kill.status_code == 200
        payload = kill.json()
        assert payload["id"] == run_id
        assert payload["killed"] is True
        assert payload["status"] == "killed"

        after = client.get("/api/v1/mission/subagents")
        assert after.status_code == 200
        assert not any(row["id"] == run_id for row in after.json()["running"])


def test_mission_subagents_kill_requires_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        run_id = _spawn_long_l1_on_client(client)
        resp = client.post(f"/api/v1/mission/subagents/{run_id}/kill")
        assert resp.status_code == 403


def test_mission_subagents_kill_all_by_role(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        run_id = _spawn_long_l1_on_client(client, task_summary="tier b work")

        resp = client.post(
            "/api/v1/mission/subagents/kill_all?role=tier_b",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["killed_count"] >= 1
        assert body["role"] == "tier_b"

        listed = client.get("/api/v1/mission/subagents")
        assert listed.status_code == 200
        assert not any(row["id"] == run_id for row in listed.json()["running"])
