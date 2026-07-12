"""Tracing section config tests."""

from __future__ import annotations

from pathlib import Path

from sevn.config import WorkspaceConfig, WorkspaceLayout
from sevn.config.workspace_config import TraceSinkEntry, TracingConfig


def test_traces_dir_from_sink(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        tracing=TracingConfig(
            sinks=[TraceSinkEntry(sink_type="jsonl_file", path="rel/trace.jsonl")],
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    lay = WorkspaceLayout(tmp_path / "sevn.json", tmp_path)
    assert lay.traces_dir(cfg) == (tmp_path / "rel").resolve()
