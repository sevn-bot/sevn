"""Batch B W7 RED — triggers API serves durable run status (#147; green after W9).

Contract (`about-sevn.bot/specs/30-non-interactive-triggers.md`): ``GET /api/v1/runs/{run_id}``
resolves status from the ``trigger_runs`` table on ``app.state.sqlite_conn`` rather than the
process-local ``app.state.trigger_run_status`` dict, so a restarted gateway still answers for
runs it accepted before the restart.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from sevn.storage.migrate import apply_migrations
from sevn.triggers.api_router import build_api_router

_TOKEN = "trigger-bearer-at-least-32-characters-long"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def migrated_conn() -> Iterator[sqlite3.Connection]:
    """In-memory ``sevn.db`` at migration head, shared with the TestClient thread."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


def _restarted_client(conn: sqlite3.Connection) -> TestClient:
    """Triggers app whose process-local status map is empty, as after a restart."""
    app = FastAPI()
    app.include_router(build_api_router())
    app.state.resolved_gateway_token = _TOKEN
    app.state.webchat_jwt_secret = None
    app.state.sqlite_conn = conn
    app.state.trigger_run_status = {}
    return TestClient(app)


def test_run_status_requires_bearer(migrated_conn: sqlite3.Connection) -> None:
    """Regression guard: durable status must stay behind triggers API auth."""
    client = _restarted_client(migrated_conn)
    assert client.get("/api/v1/runs/run-1").status_code == 401


def test_unknown_run_id_reports_unknown(migrated_conn: sqlite3.Connection) -> None:
    """Error path: an id with no row anywhere resolves to ``unknown``, not a 500."""
    client = _restarted_client(migrated_conn)
    resp = client.get("/api/v1/runs/never-dispatched", headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"run_id": "never-dispatched", "status": "unknown"}


@pytest.mark.xfail(reason="green after W9: run status read from trigger_runs", strict=False)
def test_run_status_survives_restart(migrated_conn: sqlite3.Connection) -> None:
    """A run recorded before the restart is still reported after the status map is lost."""
    migrated_conn.execute(
        "INSERT INTO trigger_runs (run_id, correlation_id, status, created_at, updated_at) "
        "VALUES ('run-restart', 'run-restart', 'completed', "
        "'2026-08-03T00:00:00Z', '2026-08-03T00:00:00Z')",
    )
    migrated_conn.commit()
    client = _restarted_client(migrated_conn)
    resp = client.get("/api/v1/runs/run-restart", headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"run_id": "run-restart", "status": "completed"}
