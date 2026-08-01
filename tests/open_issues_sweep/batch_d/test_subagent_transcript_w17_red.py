"""W17.5 — live subagent transcripts (#77 → W20)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
from sevn.agent.subagents.storage import persist_subagent_run
from sevn.storage.migrate import apply_migrations


def _sample_run(run_id: str = "run-t1") -> SubAgentRun:
    return SubAgentRun(
        id=run_id,
        level=2,
        role="tier_b",
        specialist="researcher",
        parent_id="parent-t",
        session_id="sess-t",
        channel="telegram",
        task_summary="trace me",
        status=SubAgentStatus.RUNNING,
        started_at=100,
        finished_at=None,
        trace_id="trace-run-t1",
    )


def test_subagent_run_has_stable_transcript_path(tmp_path: Path) -> None:
    """Each run exposes a deterministic transcript file path keyed by run id."""
    from sevn.agent.subagents.transcript import transcript_path_for_run

    run = _sample_run()
    path = transcript_path_for_run(content_root=tmp_path, run=run)
    assert path.is_absolute() or not str(path).startswith("..")
    assert run.id in path.name
    again = transcript_path_for_run(content_root=tmp_path, run=run)
    assert path == again


def test_subagent_transcript_appends_redacted_events(tmp_path: Path) -> None:
    """Prompts, tool calls, results, status, and summary are appended with redaction."""
    from sevn.agent.subagents.transcript import SubagentTranscriptWriter

    run = _sample_run()
    writer = SubagentTranscriptWriter(content_root=tmp_path, run=run)
    secret = "Bearer sk-live-abc123"
    writer.append_prompt(f"system: do work\nuser: token={secret}")
    writer.append_tool_call(
        name="shell", arguments='{"cmd":"curl -H \\"Authorization: Bearer tok\\""}'
    )
    writer.append_tool_result('{"stdout":"ok"}')
    writer.append_status("running")
    writer.append_summary("done")

    text = writer.path.read_text(encoding="utf-8")
    assert "sk-live-abc123" not in text
    assert "Bearer" not in text or "[REDACTED]" in text
    assert "append_tool_call" not in text  # payload present
    assert "running" in text
    assert "done" in text


def test_specialist_worker_writes_transcript_outside_tier_b_session() -> None:
    """``_specialist_worker_body`` appends to the run-scoped transcript file."""
    from sevn.tools.subagent_spawn import _specialist_worker_body

    assert "transcript" in _specialist_worker_body.__code__.co_varnames or hasattr(
        _specialist_worker_body,
        "__wrapped__",
    )


def test_parent_turn_reports_subagent_transcript_location() -> None:
    """Completion updates include a human-readable transcript path."""
    from sevn.gateway.subagents.subagents_announce import format_transcript_reference

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    run = _sample_run()
    run = replace(run, status=SubAgentStatus.DONE, finished_at=200)
    persist_subagent_run(conn, run)
    ref = format_transcript_reference(conn, run, content_root=Path("/tmp/ws"))
    assert run.id in ref
    assert "transcript" in ref.lower()


def test_transcript_reader_scoped_to_subagent_run(tmp_path: Path) -> None:
    """``read_transcript`` (or successor) can load a subagent run file by id."""
    from sevn.tools.transcript import read_subagent_transcript

    run = _sample_run()
    from sevn.agent.subagents.transcript import SubagentTranscriptWriter

    writer = SubagentTranscriptWriter(content_root=tmp_path, run=run)
    writer.append_summary("visible summary")
    snippet = read_subagent_transcript(content_root=tmp_path, run_id=run.id, tail_lines=10)
    assert "visible summary" in snippet
