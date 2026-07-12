"""Mission Control MC-10 Evolution tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    GatewayConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.evolution.approvals import create_approval
from sevn.evolution.events import evolution_issue_ws_topic
from sevn.evolution.issues import create_issue, save_issue
from sevn.evolution.spec_kit_runs import SpecKitRunRecord, append_spec_kit_run
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.workspace.layout import WorkspaceLayout

_EVOLUTION_SLUGS = frozenset(
    {"issues", "pipelines", "approvals", "spec-kit", "evolution-traces", "stats"},
)


@contextmanager
def _local_open_client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway=GatewayConfig(
            host="127.0.0.1", port=3001, token="${SECRET:keychain:sevn.gateway.token}"
        ),
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            local_open=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, client=("127.0.0.1", 0), raise_server_exceptions=True) as client:
        yield client


def test_mc10_wired_slugs_include_evolution_tabs() -> None:
    assert _EVOLUTION_SLUGS <= WIRED_SLUGS


def test_mc10_evolution_apis_local_open_without_login(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    lay = WorkspaceLayout.from_config(
        sevn_json,
        WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
    )
    active = create_issue(lay, kind="feature", title="Active", state="spec_kit")
    issue = create_issue(lay, kind="feature", title="Needs approval", state="awaiting_approval")
    approval = create_approval(
        lay,
        kind="feature_plan",
        title="Plan",
        body="body",
        issue_id=issue.id,
    )
    issue.approval_id = approval.id
    save_issue(lay, issue)

    with _local_open_client(tmp_path) as client:
        assert client.get("/api/v1/auth/status").json()["local_open"] is True
        for path in (
            "/api/v1/evolution/issues?limit=5",
            "/api/v1/evolution/pipelines",
            "/api/v1/evolution/approvals?pending_only=true",
            "/api/v1/evolution/traces?limit=5",
            "/api/v1/evolution/stats",
            "/api/v1/spec-kit/constitution",
            "/api/v1/spec-kit/options",
            "/api/v1/spec-kit/runs?limit=5",
        ):
            resp = client.get(path)
            assert resp.status_code == 200, path
        pipelines = client.get("/api/v1/evolution/pipelines").json()["items"]
        assert any(row["issue_id"] == active.id for row in pipelines)
        approvals = client.get("/api/v1/evolution/approvals").json()["items"]
        assert any(row["id"] == approval.id for row in approvals)


def test_spec_kit_runs_filter_by_job_and_issue(tmp_path: Path) -> None:
    with _local_open_client(tmp_path) as client:
        layout = client.app.state.layout
        dot = layout.dot_sevn
        dot.mkdir(parents=True, exist_ok=True)
        append_spec_kit_run(
            dot,
            SpecKitRunRecord(
                run_id="r-job",
                command="plan",
                argv=[],
                cwd="/tmp",
                status="dry_run",
                started_at="t0",
                finished_at="t1",
                owner_principal="owner",
                job_id="job-a",
            ),
        )
        append_spec_kit_run(
            dot,
            SpecKitRunRecord(
                run_id="r-issue",
                command="tasks",
                argv=[],
                cwd="/tmp",
                status="ok",
                started_at="t0",
                finished_at="t1",
                owner_principal="owner",
                issue_id="iss-b",
            ),
        )
        append_spec_kit_run(
            dot,
            SpecKitRunRecord(
                run_id="r-other",
                command="plan",
                argv=[],
                cwd="/tmp",
                status="ok",
                started_at="t0",
                finished_at="t1",
                owner_principal="owner",
            ),
        )
        by_job = client.get("/api/v1/spec-kit/runs?job_id=job-a").json()["items"]
        assert len(by_job) == 1
        assert by_job[0]["run_id"] == "r-job"
        assert by_job[0]["improve_job_id"] == "job-a"
        by_issue = client.get("/api/v1/spec-kit/runs?issue_id=iss-b").json()["items"]
        assert len(by_issue) == 1
        assert by_issue[0]["issue_id"] == "iss-b"


def test_evolution_issue_ws_local_open_receives_event(tmp_path: Path) -> None:
    topic = evolution_issue_ws_topic("iss-ws")
    with _local_open_client(tmp_path) as client, client.websocket_connect("/ws/dashboard") as ws:
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        ws.send_text(json.dumps({"type": "subscribe", "topics": [topic]}))
        subscribed = json.loads(ws.receive_text())
        assert subscribed["type"] == "subscribed"
        assert topic in subscribed["topics"]
        client.portal.call(
            client.app.state.dashboard_hub.publish,
            topic,
            {"issue_id": "iss-ws", "event": "transition", "state": "implementing"},
        )
        event = json.loads(ws.receive_text())
        assert event["topic"] == topic
        assert event["payload"]["state"] == "implementing"
