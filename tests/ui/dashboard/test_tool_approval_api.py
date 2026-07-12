"""Tests for Mission Control live tier-B tool approval API (MC W7)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.agent.adapters.tool_approval_bridge import (
    ToolApprovalBridge,
    install_tool_approval_bridge,
)
from sevn.config.workspace_config import DashboardWorkspaceConfig, WorkspaceConfig
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=False,
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"password": "pw"})
    assert resp.status_code == 200


def test_approvals_pending_requires_auth(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        remote = TestClient(
            client.app,
            client=("203.0.113.1", 40000),
            raise_server_exceptions=True,
        )
        resp = remote.get("/api/v1/agent/approvals/pending")
        assert resp.status_code == 401


def test_approvals_pending_empty_when_no_decisions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/agent/approvals/pending")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


def test_approval_decide_requires_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post("/api/v1/agent/approvals/dec-1", json={"verdict": "once"})
        assert resp.status_code == 403


def test_approval_decide_unknown_decision(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post(
            "/api/v1/agent/approvals/missing-id",
            json={"verdict": "once"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bridge_submit_unblocks_waiter(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        bridge: ToolApprovalBridge = client.app.state.tool_approval_bridge
        bridge.timeout_s = 2.0

        async def waiter() -> str:
            return await bridge.await_operator_verdict(
                session_id="sess-1",
                turn_id="turn-1",
                tool_name="delete",
                args_summary='{"path":"x.txt"}',
                trace=None,
            )

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        pending = bridge.list_pending()
        assert len(pending) == 1
        decision_id = pending[0]["decision_id"]

        _login(client)
        resp = client.post(
            f"/api/v1/agent/approvals/{decision_id}",
            json={"verdict": "once"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        assert resp.json()["verdict"] == "once"

        verdict = await asyncio.wait_for(task, timeout=2.0)
        assert verdict == "once"
        assert bridge.list_pending() == []


@pytest.mark.asyncio
async def test_approval_always_persists_human_preapproved(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        bridge: ToolApprovalBridge = client.app.state.tool_approval_bridge
        bridge.timeout_s = 2.0

        async def waiter() -> str:
            return await bridge.await_operator_verdict(
                session_id="sess-2",
                turn_id="turn-2",
                tool_name="delete",
                args_summary="{}",
                trace=None,
            )

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        decision_id = bridge.list_pending()[0]["decision_id"]

        _login(client)
        resp = client.post(
            f"/api/v1/agent/approvals/{decision_id}",
            json={"verdict": "always"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        assert await asyncio.wait_for(task, timeout=2.0) == "always"

        sevn_json = tmp_path / "sevn.json"
        body = sevn_json.read_text(encoding="utf-8")
        assert "human_preapproved" in body
        assert "delete" in body


@pytest.mark.asyncio
async def test_approval_deny_returns_verdict(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        bridge: ToolApprovalBridge = client.app.state.tool_approval_bridge
        bridge.timeout_s = 2.0

        async def waiter() -> str:
            return await bridge.await_operator_verdict(
                session_id="sess-3",
                turn_id="turn-3",
                tool_name="delete",
                args_summary="{}",
                trace=None,
            )

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        decision_id = bridge.list_pending()[0]["decision_id"]

        _login(client)
        resp = client.post(
            f"/api/v1/agent/approvals/{decision_id}",
            json={"verdict": "deny"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200
        assert await asyncio.wait_for(task, timeout=2.0) == "deny"


def test_install_tool_approval_bridge_on_app() -> None:
    from fastapi import FastAPI

    from sevn.ui.dashboard.ws import DashboardHub

    app = FastAPI()
    bridge = install_tool_approval_bridge(app, hub=DashboardHub())
    assert app.state.tool_approval_bridge is bridge
