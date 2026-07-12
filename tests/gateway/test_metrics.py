"""Gateway Prometheus metrics (`specs/17-gateway.md`)."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.http_server import create_app
from sevn.gateway.prometheus_metrics import render_gateway_metrics
from sevn.workspace.layout import WorkspaceLayout


def test_render_gateway_metrics_includes_counters() -> None:
    body = render_gateway_metrics(active_sessions=3, active_runs=1)
    assert "sevn_gateway_up 1" in body
    assert "sevn_active_sessions 3" in body
    assert "sevn_active_runs 1" in body


def test_metrics_endpoint_returns_prometheus_text(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app) as client:
        r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    assert "sevn_gateway_up" in r.text
