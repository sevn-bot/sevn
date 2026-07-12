"""Mission Control operations control-plane API tests (MC W3 §4)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from sevn.cli.errors import CliPreconditionError
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.triggers.cron import add_cron_job
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.services.ops_control import OPS_CONFIRM_TOKEN, build_backup_export_bytes
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "test-gw-token", "port": 19999},
                "self_improve": {"enabled": True, "preset": "A"},
            },
        ),
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
        gateway={"token": "test-gw-token", "port": 19999},
        self_improve={"enabled": True, "preset": "A"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_ops_capabilities_lists_confirm_token(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/ops/actions/capabilities")
        assert resp.status_code == 200
        body = resp.json()
        assert body["confirm_token"] == OPS_CONFIRM_TOKEN
        assert "reload_config" in body["actions"]


def test_ops_daemons_status(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        with (
            patch(
                "sevn.ui.dashboard.services.ops_control.probe_gateway_listen_state",
                return_value="absent",
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.probe_proxy_listen_state",
                return_value="absent",
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.unit_file_exists",
                return_value=False,
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.unit_is_active",
                return_value=False,
            ),
        ):
            resp = client.get("/api/v1/ops/daemons")
        assert resp.status_code == 200
        body = resp.json()
        assert "gateway" in body
        assert "proxy" in body


def test_ops_daemons_status_unreachable_proxy(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        with (
            patch(
                "sevn.ui.dashboard.services.ops_control.probe_gateway_listen_state",
                return_value="absent",
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.probe_proxy_listen_state",
                return_value="absent",
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.resolve_proxy_base_url",
                return_value="http://127.0.0.1:8787",
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.proxy_healthz_get",
                side_effect=CliPreconditionError("proxy unreachable"),
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.unit_file_exists",
                return_value=False,
            ),
            patch(
                "sevn.ui.dashboard.services.ops_control.unit_is_active",
                return_value=False,
            ),
        ):
            resp = client.get("/api/v1/ops/daemons")
        assert resp.status_code == 200
        body = resp.json()
        assert body["proxy"]["health"] == {
            "configured": True,
            "ok": False,
            "status_code": None,
        }


def test_reload_config_restart_required_without_router(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        client.app.state.gateway_router = None
        resp = client.post("/api/v1/ops/reload-config", headers=headers, json={})
        assert resp.status_code == 409
        assert resp.json()["status"] == "restart_required"


def test_reload_config_ok_with_mock_router(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        router = MagicMock()
        router.apply_workspace = MagicMock()
        client.app.state.gateway_router = router
        resp = client.post("/api/v1/ops/reload-config", headers=headers, json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        router.apply_workspace.assert_called_once()


def test_dreaming_run_requires_confirm(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        resp = client.post("/api/v1/ops/dreaming/run", headers=headers, json={})
        assert resp.status_code == 400


def test_dreaming_run_happy_path(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        engine = MagicMock()
        engine.run_scheduled = AsyncMock(return_value=None)
        client.app.state.dreaming_engine = engine
        resp = client.post(
            "/api/v1/ops/dreaming/run",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert resp.status_code == 200
        engine.run_scheduled.assert_awaited_once()


def test_cron_crud_and_run(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        create = client.post(
            "/api/v1/cron/jobs",
            headers=headers,
            json={
                "job_id": "daily",
                "cron_expr": "0 9 * * *",
                "timezone": "UTC",
            },
        )
        assert create.status_code == 201
        assert any(row["job_id"] == "daily" for row in create.json()["jobs"])

        update = client.put(
            "/api/v1/cron/jobs/daily",
            headers=headers,
            json={
                "job_id": "daily",
                "cron_expr": "0 10 * * *",
                "timezone": "UTC",
                "enabled": False,
            },
        )
        assert update.status_code == 200
        row = next(r for r in update.json()["jobs"] if r["job_id"] == "daily")
        assert row["enabled"] is False

        dispatch = AsyncMock()
        client.app.state.dispatch_trigger = dispatch
        run = client.post(
            "/api/v1/cron/jobs/daily/run",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert run.status_code == 200
        dispatch.assert_awaited_once()

        delete = client.request(
            "DELETE",
            "/api/v1/cron/jobs/daily",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert delete.status_code == 200
        assert "daily" not in {r["job_id"] for r in delete.json()["jobs"]}


def test_cron_run_requires_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        add_cron_job(conn, job_id="x", cron_expr="0 9 * * *")
        conn.commit()
        resp = client.post(
            "/api/v1/cron/jobs/x/run",
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert resp.status_code == 403


def test_snapshot_create_and_restore_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        marker = tmp_path / "marker.txt"
        marker.write_text("before", encoding="utf-8")
        create = client.post(
            "/api/v1/ops/snapshots",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert create.status_code == 201
        snapshot_id = create.json()["snapshot_id"]
        marker.write_text("after", encoding="utf-8")
        restore = client.post(
            f"/api/v1/ops/snapshots/{snapshot_id}/restore",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert restore.status_code == 200
        assert marker.read_text(encoding="utf-8") == "before"


def test_backup_export_import_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        layout: WorkspaceLayout = client.app.state.layout
        archive = build_backup_export_bytes(layout)
        backup = tmp_path / "sevn.json.v9"
        backup.write_text('{"schema_version": 1}', encoding="utf-8")
        import_resp = client.post(
            "/api/v1/ops/backup/import",
            headers=headers,
            files={"archive": ("backup.tar.gz", archive, "application/gzip")},
            data={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert import_resp.status_code == 200
        assert "sevn.json" in import_resp.json()["imported"]


def test_daemon_action_requires_confirm(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        resp = client.post(
            "/api/v1/ops/daemons/gateway/enable",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400


def test_daemon_enable_mocked(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        with patch(
            "sevn.ui.dashboard.api.ops_control.daemon_control",
            return_value={"ok": True, "detail": "ok"},
        ):
            resp = client.post(
                "/api/v1/ops/daemons/gateway/enable",
                headers=headers,
                json={"confirm_token": OPS_CONFIRM_TOKEN},
            )
        assert resp.status_code == 200


def test_self_improve_cycle_confirm_gated(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        enqueue = AsyncMock(return_value="job-1")
        client.app.state.enqueue_improve_job = enqueue
        resp = client.post(
            "/api/v1/self_improve/cycle",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "job-1"
        enqueue.assert_awaited_once()


def test_skill_install_uninstall_user_only(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        bundled = client.get("/api/v1/agent/skills/bundled")
        assert bundled.status_code == 200
        names = bundled.json()["skills"]
        if not names:
            return
        skill_name = names[0]
        install = client.post(
            "/api/v1/agent/skills/install",
            headers=headers,
            json={"skill_name": skill_name, "confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert install.status_code == 201
        uninstall = client.request(
            "DELETE",
            f"/api/v1/agent/skills/{skill_name}",
            headers=headers,
            json={"confirm_token": OPS_CONFIRM_TOKEN},
        )
        assert uninstall.status_code == 200


def test_ops_daemons_status_degraded_on_probe_exception(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        with patch(
            "sevn.ui.dashboard.api.ops_control.build_daemons_status",
            side_effect=RuntimeError("daemon probe failed"),
        ):
            resp = client.get("/api/v1/ops/daemons")
        assert resp.status_code == 200
        body = resp.json()
        assert body["degraded"] is True
        assert "daemon probe failed" in body["gateway"]["health"]["detail"]
