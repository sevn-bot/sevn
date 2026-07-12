"""Mission Control MC-6 Ops tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

if TYPE_CHECKING:
    import pytest

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
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "channels": {"telegram": {"enabled": true, "bot_token": "${SECRET:k:telegram.bot_token}"}}, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
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


def test_mc6_wired_slugs_include_ops_tabs() -> None:
    expected = {
        "cron",
        "security",
        "secrets",
        "egress-proxy",
        "tunnels-infra",
        "backup-snapshots",
        "config",
        "schema-ontology",
    }
    assert expected <= WIRED_SLUGS


def test_config_get_redacts_secret_refs(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        doc = body["document"]
        assert "telegram.bot_token" not in str(doc)
        assert "${SECRET" not in str(doc)
        assert "<redacted>" in str(doc)


def test_cron_jobs_list_returns_persisted_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        add_cron_job(conn, job_id="daily", cron_expr="0 9 * * *")
        conn.commit()
        resp = client.get("/api/v1/cron/jobs")
        assert resp.status_code == 200
        body = resp.json()
        job_ids = {row["job_id"] for row in body["jobs"]}
        assert "daily" in job_ids


def test_secrets_aliases_lists_logical_keys_only(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/secrets/aliases")
        assert resp.status_code == 200
        body = resp.json()
        keys = {row["logical_key"] for row in body["aliases"]}
        assert "telegram.bot_token" in keys
        assert "supersecret" not in resp.text


def test_security_put_updates_scanner_toggle(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        headers = _csrf_headers(client)
        resp = client.put(
            "/api/v1/security",
            json={"security": {"scanner": {"heuristic_only": False, "image_ocr": True}}},
            headers=headers,
        )
        assert resp.status_code == 200
        on_disk = json.loads((tmp_path / "sevn.json").read_text(encoding="utf-8"))
        scanner = on_disk["security"]["scanner"]
        assert scanner["heuristic_only"] is False
        assert scanner["image_ocr"] is True


def test_backup_manifest_lists_config_backup(tmp_path: Path) -> None:
    backup = tmp_path / "sevn.json.v1"
    backup.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/backup/manifest")
        assert resp.status_code == 200
        names = {row["name"] for row in resp.json()["config_backups"]}
        assert "sevn.json.v1" in names


def test_tunnels_status_includes_gateway_and_probes(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        with (
            patch(
                "sevn.ui.dashboard.api.ops.probe_secrets_backend",
            ) as secrets_probe,
            patch(
                "sevn.ui.dashboard.api.ops.probe_llm_reachability",
            ) as llm_probe,
        ):
            from sevn.onboarding.live_validate import ValidationCheck

            secrets_probe.return_value = ValidationCheck("secrets", True, "info", "ok")
            llm_probe.return_value = ValidationCheck("llm", True, "info", "ok")
            resp = client.get("/api/v1/tunnels/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "tunnel_mode" in body
        assert "gateway_host" in body
        assert len(body["probes"]) >= 2


def test_tunnels_status_does_not_apply_workspace(tmp_path: Path) -> None:
    apply = MagicMock()
    mock_router = MagicMock()
    mock_router.apply_workspace = apply
    with _client(tmp_path) as client:
        client.app.state.gateway_router = mock_router
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        with (
            patch(
                "sevn.ui.dashboard.api.ops.probe_secrets_backend",
            ) as secrets_probe,
            patch(
                "sevn.ui.dashboard.api.ops.probe_llm_reachability",
            ) as llm_probe,
        ):
            from sevn.onboarding.live_validate import ValidationCheck

            secrets_probe.return_value = ValidationCheck("secrets", True, "info", "ok")
            llm_probe.return_value = ValidationCheck("llm", True, "info", "ok")
            resp = client.get("/api/v1/tunnels/status")
        assert resp.status_code == 200
        apply.assert_not_called()


def test_tunnels_status_tunnel_flags_match_layout_sevn_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tunnel_mode`` / ``tunnel_active`` must follow layout ``sevn.json``, not SEVN_HOME."""
    layout_json = tmp_path / "layout" / "sevn.json"
    bound_json = tmp_path / "bound" / "sevn.json"
    layout_json.parent.mkdir(parents=True)
    bound_json.parent.mkdir(parents=True)
    layout_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "channels": {
                    "telegram": {
                        "enabled": True,
                        "bot_token": "${SECRET:k:telegram.bot_token}",
                    },
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "infrastructure": {"tunnel": {"mode": "cloudflare", "hostname": "bot.example.com"}},
            },
        ),
        encoding="utf-8",
    )
    bound_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "infrastructure": {"tunnel": {"mode": "none"}},
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sevn.config.loader.bound_sevn_json_path", lambda: bound_json)

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
        infrastructure={"tunnel": {"mode": "none"}},
    )
    layout = WorkspaceLayout.from_config(layout_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        with (
            patch("sevn.ui.dashboard.api.ops.probe_secrets_backend") as secrets_probe,
            patch("sevn.ui.dashboard.api.ops.probe_llm_reachability") as llm_probe,
        ):
            from sevn.onboarding.live_validate import ValidationCheck

            secrets_probe.return_value = ValidationCheck("secrets", True, "info", "ok")
            llm_probe.return_value = ValidationCheck("llm", True, "info", "ok")
            resp = client.get("/api/v1/tunnels/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tunnel_mode"] == "cloudflare"
        assert body["tunnel_active"] is True
        assert body["tunnel"]["mode"] == "cloudflare"


def test_schema_ontology_returns_schema_and_index(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/schema/ontology")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_available"] is True
        assert body["property_count"] > 0
        ontology = body["ontology"]
        if ontology.get("available"):
            assert len(ontology["entries"]) > 0


def test_schema_ontology_survives_unresolved_repo_root(tmp_path: Path) -> None:
    from sevn.cli.repo_sync import RepoSyncError
    from sevn.ui.dashboard.api import ops as ops_api

    with patch.object(ops_api, "resolve_sevn_repo_root", side_effect=RepoSyncError("no checkout")):
        payload = ops_api._ontology_index_payload()
    assert payload["available"] is False
    assert payload["reason"] == "repo_root_unresolved"

    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        with patch.object(
            ops_api, "resolve_sevn_repo_root", side_effect=RepoSyncError("no checkout")
        ):
            resp = client.get("/api/v1/schema/ontology")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_available"] is True
        assert body["ontology"]["available"] is False
