"""Live per-run subagent transcripts with redaction (#77; `specs/36-sub-agents.md`).

Module: sevn.agent.subagents.transcript
Depends: json, pathlib, sqlite3, time, sevn.agent.subagents.models,
    sevn.agent.tracing.redacting_sink, sevn.logging.log_redact

Exports:
    transcript_path_for_run — stable workspace-relative JSONL path for one run.
    transcript_relpath_for_run — same path as a string relative to content root.
    SubagentTranscriptWriter — append-only redacted transcript writer.
    load_subagent_transcript_path — read persisted path from SQLite when present.

Examples:
    >>> from pathlib import Path
    >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
    >>> run = SubAgentRun(
    ...     id="a1f3", level=2, role="tier_b", specialist=None, parent_id="p1",
    ...     session_id="s", channel="c", task_summary="t",
    ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
    ... )
    >>> path = transcript_path_for_run(content_root=Path("/tmp/ws"), run=run)
    >>> run.id in path.name
    True
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from typing import TYPE_CHECKING

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.logging.log_redact import redact_log_line

if TYPE_CHECKING:
    import sqlite3

    from sevn.agent.subagents.models import SubAgentRun

_TRANSCRIPTS_DIR = Path("subagents") / "transcripts"
# Shorter sk- tail than trace sink defaults — transcript lines are single-line secrets.
_TRANSCRIPT_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9-]{8,}")


def transcript_relpath_for_run(run: SubAgentRun) -> str:
    """Return the workspace-relative JSONL path for one sub-agent run.

    Args:
        run (SubAgentRun): Target run row.

    Returns:
        str: Path like ``subagents/transcripts/<run_id>.jsonl``.

    Examples:
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> run = SubAgentRun(
        ...     id="run-t1", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s", channel="c", task_summary="t",
        ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
        ... )
        >>> transcript_relpath_for_run(run)
        'subagents/transcripts/run-t1.jsonl'
    """
    return str(_TRANSCRIPTS_DIR / f"{run.id}.jsonl")


def transcript_path_for_run(*, content_root: Path, run: SubAgentRun) -> Path:
    """Resolve the absolute transcript file path for one sub-agent run.

    Args:
        content_root (Path): Workspace content root (``content_root`` / ``workspace_path``).
        run (SubAgentRun): Target run row.

    Returns:
        Path: Absolute path to the run's JSONL transcript file.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
        >>> run = SubAgentRun(
        ...     id="run-t1", level=2, role="tier_b", specialist=None, parent_id="p1",
        ...     session_id="s", channel="c", task_summary="t",
        ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
        ... )
        >>> path = transcript_path_for_run(content_root=Path("/tmp/ws"), run=run)
        >>> path.is_absolute()
        True
    """
    return (content_root / transcript_relpath_for_run(run)).resolve()


def load_subagent_transcript_path(conn: sqlite3.Connection, run_id: str) -> str | None:
    """Load a persisted ``transcript_path`` for one run id when present.

    Args:
        conn (sqlite3.Connection): Open, migrated ``sevn.db`` connection.
        run_id (str): Target sub-agent run id.

    Returns:
        str | None: Stored relative path or ``None`` when absent.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> conn = sqlite3.connect(":memory:")
        >>> apply_migrations(conn)
        >>> load_subagent_transcript_path(conn, "missing") is None
        True
    """
    row = conn.execute(
        "SELECT transcript_path FROM subagent_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    text = str(row[0]).strip()
    return text or None


def _redact_text(text: str, policy: TraceRedactionPolicy) -> str:
    """Apply log-line and trace-pattern redaction to one transcript line.

    Args:
        text (str): Raw operator/model text.
        policy (TraceRedactionPolicy): Active redaction rules.

    Returns:
        str: Redacted text safe for persistence.

    Examples:
        >>> _redact_text("token=abc123", TraceRedactionPolicy.from_defaults())
        '<redacted>'
    """
    line = redact_log_line(text)
    for _ in range(3):
        next_line = redact_log_line(line)
        if next_line == line:
            break
        line = next_line
    if policy.enabled:
        for pattern in policy._compiled_patterns:
            line = pattern.sub("<redacted>", line)
        line = _TRANSCRIPT_SK_PATTERN.sub("<redacted>", line)
        redacted = redact_attrs({"text": line}, policy)
        value = redacted.get("text", line)
        line = str(value)
    return line


@dataclass
class SubagentTranscriptWriter:
    """Append-only JSONL writer for one sub-agent run transcript."""

    content_root: Path
    run: SubAgentRun
    conn: sqlite3.Connection | None = None
    _policy: TraceRedactionPolicy | None = None

    def __post_init__(self) -> None:
        """Ensure the transcript directory exists and persist the path when wired.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.path.name.endswith(".jsonl")
            True
        """
        self._policy = self._policy or TraceRedactionPolicy.from_defaults()
        self.path = transcript_path_for_run(content_root=self.content_root, run=self.run)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        if self.conn is not None:
            rel = transcript_relpath_for_run(self.run)
            self.conn.execute(
                "UPDATE subagent_runs SET transcript_path = ? WHERE id = ?",
                (rel, self.run.id),
            )
            if self.conn.in_transaction:
                self.conn.commit()

    @property
    def policy(self) -> TraceRedactionPolicy:
        """Active redaction policy for this writer.

        Returns:
            TraceRedactionPolicy: Resolved policy (defaults when unset).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run).policy.enabled
            True
        """
        return self._policy or TraceRedactionPolicy.from_defaults()

    def _append_event(self, event: dict[str, object]) -> None:
        """Append one redacted JSON object as a line to the transcript file.

        Args:
            event (dict[str, object]): Raw event payload (``event`` key required).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.append_status("running")
            >>> "running" in writer.path.read_text(encoding="utf-8")
            True
        """
        payload = dict(event)
        if "text" in payload and isinstance(payload["text"], str):
            payload["text"] = _redact_text(payload["text"], self.policy)
        if "arguments" in payload and isinstance(payload["arguments"], str):
            payload["arguments"] = _redact_text(payload["arguments"], self.policy)
        if "status" in payload and isinstance(payload["status"], str):
            payload["status"] = _redact_text(payload["status"], self.policy)
        payload.setdefault("ts_ns", time_ns())
        payload.setdefault("run_id", self.run.id)
        if self.run.trace_id:
            payload.setdefault("trace_id", self.run.trace_id)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def append_prompt(self, text: str) -> None:
        """Append a prompt/system/user message event.

        Args:
            text (str): Raw prompt text (redacted before persistence).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.append_prompt("hello")
            >>> '"event": "prompt"' in writer.path.read_text(encoding="utf-8")
            True
        """
        self._append_event({"event": "prompt", "text": text})

    def append_tool_call(self, *, name: str, arguments: str) -> None:
        """Append a tool invocation event.

        Args:
            name (str): Tool name.
            arguments (str): Serialized arguments (redacted before persistence).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.append_tool_call(name="read", arguments="{}")
            >>> '"event": "tool_call"' in writer.path.read_text(encoding="utf-8")
            True
        """
        self._append_event({"event": "tool_call", "name": name, "arguments": arguments})

    def append_tool_result(self, text: str) -> None:
        """Append a tool result event.

        Args:
            text (str): Serialized tool result (redacted before persistence).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.append_tool_result("ok")
            >>> '"event": "tool_result"' in writer.path.read_text(encoding="utf-8")
            True
        """
        self._append_event({"event": "tool_result", "text": text})

    def append_status(self, status: str) -> None:
        """Append a lifecycle/status transition event.

        Args:
            status (str): Status label (for example ``running`` or ``done``).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.append_status("done")
            >>> '"status": "done"' in writer.path.read_text(encoding="utf-8")
            True
        """
        self._append_event({"event": "status", "status": status})

    def append_summary(self, text: str) -> None:
        """Append the final completion summary event.

        Args:
            text (str): Completion summary (redacted before persistence).

        Examples:
            >>> from pathlib import Path
            >>> from sevn.agent.subagents.models import SubAgentRun, SubAgentStatus
            >>> run = SubAgentRun(
            ...     id="a1", level=2, role="tier_b", specialist=None, parent_id="p",
            ...     session_id="s", channel="c", task_summary="t",
            ...     status=SubAgentStatus.RUNNING, started_at=1, finished_at=None, trace_id=None,
            ... )
            >>> writer = SubagentTranscriptWriter(content_root=Path("/tmp/ws"), run=run)
            >>> writer.append_summary("finished")
            >>> '"event": "summary"' in writer.path.read_text(encoding="utf-8")
            True
        """
        self._append_event({"event": "summary", "text": text})


__all__ = [
    "SubagentTranscriptWriter",
    "load_subagent_transcript_path",
    "transcript_path_for_run",
    "transcript_relpath_for_run",
]
