"""Gateway default tracing sink wiring (Wave T-0A)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

from sevn.agent.tracing.sink import NullTraceSink
from sevn.agent.tracing.sink_factory import build_gateway_trace_sink
from sevn.config.defaults import DEFAULT_TRACING_SINKS
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.workspace.layout import WorkspaceLayout


def _layout(tmp_path: Path) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    sinks = [TraceSinkEntry.model_validate(entry) for entry in DEFAULT_TRACING_SINKS]
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=sinks),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    return layout, workspace_cfg


def test_default_tracing_sinks_yield_non_null_sink(tmp_path: Path) -> None:
    layout, workspace_cfg = _layout(tmp_path)

    sink = build_gateway_trace_sink(workspace_cfg, layout)

    assert not isinstance(sink, NullTraceSink)


def test_default_tracing_sinks_gateway_boot_persists_sqlite_and_dated_jsonl(
    tmp_path: Path,
) -> None:
    layout, workspace_cfg = _layout(tmp_path)

    app = create_app(workspace=workspace_cfg, layout=layout)
    with TestClient(app, raise_server_exceptions=True) as client:
        client.get("/health")

    assert (layout.dot_sevn / "traces.db").is_file()

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    jsonl_path = layout.dot_sevn / "traces" / f"{today}.jsonl"
    assert jsonl_path.is_file()
    kinds = [
        json.loads(line)["kind"]
        for line in jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert "gateway.boot" in kinds
