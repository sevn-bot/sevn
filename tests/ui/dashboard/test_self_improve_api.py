"""Dashboard self-improve eval report API (`plan/full-tracing-eval-wave-plan.md` E-3)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.self_improve.jobs.store import enqueue_job_row, update_job_state
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


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
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
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


@contextmanager
def _csrf_client(tmp_path: Path) -> Iterator[TestClient]:
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
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
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


def _csrf_login(client: TestClient) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert resp.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_eval_report_returns_redacted_segments(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn = client.app.state.sqlite_conn
        job_id = enqueue_job_row(
            conn,
            workspace_id="w",
            experiment_id="e",
            preset="A",
            sampler_seed=1,
            correlation_id=None,
            client_token=None,
            experiment_snapshot={},
        )
        report_path = tmp_path / "eval_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "passed": True,
                    "segments": [
                        {"name": "unit", "status": "passed", "detail": "ok"},
                        {"name": "golden_routing", "status": "passed", "detail": "0.98"},
                    ],
                    "password": "secret-value",
                    "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                },
            ),
            encoding="utf-8",
        )
        update_job_state(
            conn,
            job_id=job_id,
            state="awaiting_review",
            eval_report_path=str(report_path),
        )
        resp = client.get(f"/api/v1/self_improve/jobs/{job_id}/eval_report")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == job_id
        report = body["report"]
        assert report["passed"] is True
        assert len(report["segments"]) == 2
        assert report["password"] == "<redacted>"


def test_eval_report_missing_returns_404(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/self_improve/jobs/missing-job/eval_report")
        assert resp.status_code == 404


def test_list_jobs_returns_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn = client.app.state.sqlite_conn
        job_id = enqueue_job_row(
            conn,
            workspace_id="w",
            experiment_id="e",
            preset="B",
            sampler_seed=2,
            correlation_id=None,
            client_token=None,
            experiment_snapshot={},
        )
        resp = client.get("/api/v1/self_improve/jobs")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(row["job_id"] == job_id for row in items)


def test_create_job_requires_csrf(tmp_path: Path) -> None:
    with _csrf_client(tmp_path) as client:
        _csrf_login(client)
        resp = client.post("/api/v1/self_improve/jobs", json={"experiment_id": "default"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "csrf_failed"


def test_create_job_with_csrf_passes_guard(tmp_path: Path) -> None:
    with _csrf_client(tmp_path) as client:
        headers = _csrf_login(client)
        client.app.state.enqueue_improve_job = None
        resp = client.post(
            "/api/v1/self_improve/jobs",
            json={"experiment_id": "default"},
            headers=headers,
        )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "self_improve_unavailable"


def test_approve_plan_requires_csrf(tmp_path: Path) -> None:
    with _csrf_client(tmp_path) as client:
        _csrf_login(client)
        resp = client.post("/api/v1/self_improve/jobs/job-1/approve_plan")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "csrf_failed"


def test_approve_plan_with_csrf_passes_guard(tmp_path: Path) -> None:
    with _csrf_client(tmp_path) as client:
        headers = _csrf_login(client)
        resp = client.post(
            "/api/v1/self_improve/jobs/missing-job/approve_plan",
            headers=headers,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "job_not_found"
