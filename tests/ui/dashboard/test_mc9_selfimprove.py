"""Mission Control MC-9 Self-improve tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    RlmWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    SelfImproveWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT, create_app
from sevn.gateway.webapp.webapp_qa import insert_structured_feedback
from sevn.self_improve.feedback import insert_feedback_event
from sevn.self_improve.jobs.store import enqueue_job_row, update_job_state
from sevn.self_improve.trajectories.ingest import ingest_trajectory_facts_from_traces
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "rlm": {"c_d_backend": "dspy", "repl_lifetime": "per_turn"},
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        rlm=RlmWorkspaceConfig(c_d_backend="dspy", repl_lifetime="per_turn"),
        self_improve=SelfImproveWorkspaceConfig(enabled=True, preset="A"),
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


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_mc9_wired_slugs_include_self_improve_tabs() -> None:
    expected = {
        "jobs",
        "trajectories",
        "feedback",
        "rlm-training",
        "experiments-metrics",
    }
    assert expected <= WIRED_SLUGS


def test_self_improve_feedback_lists_events_and_structured(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        insert_feedback_event(
            conn,
            kind="thumbs_down",
            target_turn_id="turn-1",
            schema_version=1,
            payload={"note": "bad"},
        )
        insert_structured_feedback(
            conn,
            target_turn_id="turn-2",
            user_id="owner",
            channel="webchat",
            platform_message_id=None,
            body_text="too verbose",
            dropdowns={"severity": "minor"},
        )
        resp = client.get("/api/v1/self_improve/feedback?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) >= 1
        assert body["events"][0]["kind"] == "thumbs_down"
        assert len(body["structured"]) >= 1
        assert body["structured"][0]["channel"] == "webchat"


def test_self_improve_trajectories_empty_without_ingest(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/self_improve/trajectories?limit=10")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


def test_self_improve_trajectories_lists_facts(tmp_path: Path) -> None:
    """Trajectories API lists rows produced by ``ingest_trajectory_facts_from_traces``."""
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        layout: WorkspaceLayout = client.app.state.layout
        layout.dot_sevn.mkdir(parents=True, exist_ok=True)
        traces_path = traces_sqlite_path(layout.dot_sevn)
        tconn = sqlite3.connect(traces_path)
        apply_traces_migrations(tconn)
        tconn.execute(
            """INSERT INTO trace_events (
                span_id, parent_span_id, session_id, turn_id, tier, kind,
                ts_start_ns, ts_end_ns, status, attrs_json
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'ok', ?)""",
            (
                "span-t1",
                "s1",
                "t1",
                "C",
                "triage.complete",
                100,
                101,
                json.dumps(
                    {
                        "intent": "chat",
                        "complexity": "C",
                        "channel": "telegram",
                        "budget_regime": "normal",
                        "model_id": "minimax/MiniMax-M2.7",
                    },
                ),
            ),
        )
        tconn.commit()
        tconn.close()
        result = ingest_trajectory_facts_from_traces(conn, traces_path)
        assert result.rows_upserted == 1
        resp = client.get("/api/v1/self_improve/trajectories?limit=10")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["turn_id"] == "t1"
        assert items[0]["tier"] == "C"


def test_self_improve_rlm_training_read_only_summary(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        enqueue_job_row(
            conn,
            workspace_id=".",
            experiment_id="exp-a",
            preset="A",
            sampler_seed=1,
            correlation_id=None,
            client_token=None,
            experiment_snapshot={"experiment_id": "exp-a"},
        )
        resp = client.get("/api/v1/self_improve/rlm-training")
        assert resp.status_code == 200
        body = resp.json()
        assert body["read_only"] is True
        assert body["rlm"]["c_d_backend"] == "dspy"
        assert body["self_improve"]["enabled"] is True
        assert body["jobs"]["by_state"].get("queued", 0) >= 1


def test_self_improve_experiments_aggregate_jobs(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        job_id = enqueue_job_row(
            conn,
            workspace_id=".",
            experiment_id="exp-b",
            preset="B",
            sampler_seed=2,
            correlation_id=None,
            client_token=None,
            experiment_snapshot={"experiment_id": "exp-b"},
        )
        report_path = tmp_path / "eval.json"
        report_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "passed": True,
                    "segments": [{"name": "unit", "status": "passed", "detail": ""}],
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
        resp = client.get("/api/v1/self_improve/experiments?limit=10")
        assert resp.status_code == 200
        experiments = resp.json()["experiments"]
        match = next(e for e in experiments if e["experiment_id"] == "exp-b")
        assert match["job_count"] >= 1
        assert match["eval_passed"] is True


def test_app_js_self_improve_panel_wiring() -> None:
    js = (MISSION_CONTROL_SPA_ROOT / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/self_improve/feedback" in js
    assert "/api/v1/self_improve/trajectories" in js
    assert "/api/v1/self_improve/rlm-training" in js
    assert "/api/v1/self_improve/experiments" in js
    assert "renderTrajectories" in js
    assert "renderFeedback" in js
    assert "renderRlmConfig" in js
    assert "renderExperimentsMetrics" in js


def test_self_improve_routes_require_auth(tmp_path: Path) -> None:
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
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app, client=("203.0.113.1", 40000), raise_server_exceptions=True) as client:
        assert client.get("/api/v1/self_improve/feedback").status_code == 401
