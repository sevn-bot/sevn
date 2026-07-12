"""Self-improve trace span kinds (`specs/33-self-improvement.md` §7, Wave T-3)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sevn.config.loader import load_workspace
from sevn.config.workspace_config import WorkspaceConfig
from sevn.self_improve.facade import (
    enqueue_improve_job,
    ensure_preset_c_auto_merge_allowed,
    run_improve_job_eval,
)
from sevn.self_improve.types import OwnerPrincipal
from sevn.storage.migrate import apply_migrations

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _RecordingSink:
    """Capture ``emit`` payloads for assertions."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _kinds(events: list[TraceEvent]) -> list[str]:
    return [event.kind for event in events]


@pytest.mark.asyncio
async def test_enqueue_emits_job_start_and_shortlist_ready(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sevn_json)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sink = _RecordingSink()
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")

    job_id = await enqueue_improve_job(
        workspace_id="ws",
        experiment_id="exp-1",
        trigger="manual",
        correlation_id="corr-1",
        owner_principal=principal,
        workspace_config=cfg,
        layout=layout,
        sqlite_conn=conn,
        trace_sink=sink,
    )

    kinds = _kinds(sink.events)
    assert kinds == [
        "self_improve.job_start",
        "self_improve.shortlist_ready",
    ]
    start = sink.events[0]
    assert start.attrs["job_id"] == job_id
    assert start.attrs["sampler_seed"] >= 0
    assert start.attrs["preset"] == "A"
    assert start.attrs["experiment_snapshot_id"] == "exp-1"
    assert start.attrs["correlation_id"] == "corr-1"
    shortlist = sink.events[1]
    assert shortlist.attrs["shortlist_count"] == 0
    assert str(shortlist.attrs["deterministic_scores_digest"]).startswith("sha256:")
    conn.close()


@pytest.mark.asyncio
async def test_run_improve_job_eval_emits_segment_spans(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sevn_json)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sink = _RecordingSink()
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")

    job_id = await enqueue_improve_job(
        workspace_id="ws",
        experiment_id="exp-1",
        trigger="manual",
        correlation_id=None,
        owner_principal=principal,
        workspace_config=cfg,
        layout=layout,
        sqlite_conn=conn,
        trace_sink=None,
    )
    result = await run_improve_job_eval(
        workspace_config=cfg,
        layout=layout,
        job_id=job_id,
        sampler_seed=42,
        experiment_id="exp-1",
        correlation_id=None,
        trace_sink=sink,
        repo_root=_REPO_ROOT,
    )
    assert result.passed is True
    starts = [event for event in sink.events if event.kind == "self_improve.eval.segment_start"]
    dones = [event for event in sink.events if event.kind == "self_improve.eval.segment_done"]
    assert len(starts) == len(result.segments)
    assert len(dones) == len(result.segments)
    assert {event.attrs["segment"] for event in starts} >= {"unit", "golden_routing"}
    conn.close()


@pytest.mark.asyncio
async def test_promotion_blocked_eval_emitted_on_preset_c_gate(tmp_path: Path) -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        self_improve={
            "enabled": True,
            "preset": "C",
            "auto_merge_enabled": True,
            "hub": {"repo": "owner/repo"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    sink = _RecordingSink()
    with pytest.raises(RuntimeError, match="auto-merge blocked"):
        ensure_preset_c_auto_merge_allowed(
            workspace_config=ws,
            eval_report_path=None,
            trace_sink=sink,
            job_id="job-blocked",
            sampler_seed=7,
            experiment_id="exp-c",
            correlation_id="corr-c",
        )
    await asyncio.sleep(0)
    blocked = [
        event for event in sink.events if event.kind == "self_improve.promotion_blocked_eval"
    ]
    assert len(blocked) == 1
    assert blocked[0].status == "blocked"
    assert blocked[0].attrs["preset"] == "C"
    assert blocked[0].attrs["experiment_snapshot_id"] == "exp-c"


def test_gateway_enqueue_wires_trace_sink(tmp_path: Path) -> None:
    from starlette.testclient import TestClient

    from sevn.config.workspace_config import TraceSinkEntry, TracingConfig
    from sevn.gateway.http_server import create_app
    from sevn.workspace.layout import WorkspaceLayout

    root = tmp_path
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        self_improve={"enabled": True, "preset": "A"},
        tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate({"type": "sqlite"})]),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)

    def _memory_sqlite_factory() -> sqlite3.Connection:
        cx = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(cx)
        return cx

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=_memory_sqlite_factory,
    )
    client = TestClient(app, raise_server_exceptions=True)

    async def _probe() -> list[str]:
        sink = _RecordingSink()
        client.app.state.gateway_trace = sink
        principal = OwnerPrincipal(principal_kind="owner", principal_id="me")
        await client.app.state.enqueue_improve_job(
            workspace_id="ws",
            experiment_id="exp-gw",
            trigger="manual",
            correlation_id="corr-gw",
            owner_principal=principal,
        )
        return _kinds(sink.events)

    with client:
        client.get("/ready")
        assert hasattr(client.app.state, "enqueue_improve_job")
        kinds = asyncio.run(_probe())
    assert kinds[:2] == [
        "self_improve.job_start",
        "self_improve.shortlist_ready",
    ]
