"""Gateway-owned Triager audit rows (`specs/13-rlm-triager.md` §10.2, `specs/17-gateway.md` §3).

Module: sevn.gateway.triage_audit
Depends: json, sqlite3, uuid, sevn.agent.triager, sevn.config.workspace_config

Exports:
    persist_triage_decision — INSERT one ``triage_decisions`` row after ``triage_turn``.
"""

from __future__ import annotations

import sqlite3
import uuid

from sevn.agent.triager.models import TriageResult
from sevn.agent.triager.run import resolve_triager_model_id
from sevn.config.workspace_config import WorkspaceConfig


def _workspace_id(workspace: WorkspaceConfig) -> str:
    """Return stable workspace id for SQLite audit rows.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        str: ``workspace_root`` when set, else empty string.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _workspace_id(WorkspaceConfig.minimal(workspace_root="/w"))
        '/w'
    """
    return str(workspace.workspace_root or "")


def _c_d_backend_label(workspace: WorkspaceConfig) -> str:
    """Resolve C/D backend label for audit storage.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        str: ``rlm.c_d_backend`` when configured, else empty string.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _c_d_backend_label(WorkspaceConfig.minimal())
        ''
    """
    rlm = workspace.rlm
    if rlm is None:
        return ""
    return str(rlm.c_d_backend or "")


def persist_triage_decision(
    conn: sqlite3.Connection,
    *,
    workspace: WorkspaceConfig,
    session_id: str,
    turn_id: str,
    triage: TriageResult,
    registry_version: int,
    personality_version: int,
    triager_model_id: str | None = None,
    triager_span_id: str | None = None,
) -> None:
    """Insert one ``triage_decisions`` row (gateway-owned, not ``triage_turn``).

    Uses ``INSERT OR IGNORE`` on ``UNIQUE (workspace_id, turn_id)`` so duplicate
    correlation ids do not raise.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        workspace (WorkspaceConfig): Parsed workspace configuration.
        session_id (str): Owning gateway session id.
        turn_id (str): Turn / correlation id for this dispatch.
        triage (TriageResult): Finalised Triager output.
        registry_version (int): Registry snapshot version at triage time.
        personality_version (int): Personality block version at triage time.
        triager_model_id (str | None): Override model id; defaults to workspace slot.
        triager_span_id (str | None): Trace span id when known; else generated.

    Examples:
        >>> import sqlite3
        >>> from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> ws = WorkspaceConfig.minimal(
        ...     workspace_root="/w",
        ...     providers={"tier_default": {"triager": "stub/t"}},
        ... )
        >>> triage = TriageResult(
        ...     intent=Intent.NEW_REQUEST,
        ...     complexity=ComplexityTier.B,
        ...     first_message="ok",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.9,
        ...     requires_vision=False,
        ...     requires_document=False,
        ...     disregard=False,
        ... )
        >>> persist_triage_decision(
        ...     c,
        ...     workspace=ws,
        ...     session_id="s1",
        ...     turn_id="t1",
        ...     triage=triage,
        ...     registry_version=1,
        ...     personality_version=0,
        ... )
        >>> int(c.execute("SELECT COUNT(*) FROM triage_decisions").fetchone()[0])
        1
    """
    model_id = triager_model_id or resolve_triager_model_id(workspace)
    span_id = triager_span_id or uuid.uuid4().hex
    conn.execute(
        """
        INSERT OR IGNORE INTO triage_decisions (
            workspace_id, session_id, turn_id, triager_span_id,
            triage_result_json, registry_version, personality_version,
            triager_model_id, c_d_backend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _workspace_id(workspace),
            session_id,
            turn_id,
            span_id,
            triage.model_dump_json(),
            int(registry_version),
            int(personality_version),
            model_id,
            _c_d_backend_label(workspace),
        ),
    )
    conn.commit()
