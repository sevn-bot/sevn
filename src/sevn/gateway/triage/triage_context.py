"""Gateway builders for Triager inputs (`specs/17-gateway.md` §2.6 Wave 2-8).

Module: sevn.gateway.triage.triage_context
Depends: sevn.agent.triager, sevn.config.defaults, sevn.tools.registry, sevn.workspace.layout

Exports:
    is_triager_enabled — read ``TRIAGER_ENABLED`` env (default on).
    passthrough_triage_result — synthetic tier-B row when Triager is disabled.
    registry_snapshot_from_tool_set — map ``ToolSet`` → ``RegistrySnapshot``.
    session_view_from_session — ``SessionView`` from gateway SQLite rows.
    load_workspace_personality — ``SOUL/IDENTITY/USER/MEMORY`` bundle + version token.
    tier_b_personality_instructions — tier-B executor persona block (anti vendor/model leak).
    lcm_summary_stub_for_session — newest LCM compaction excerpt for Triager suffix.
    triage_context_from_session — ``TriagePromptContext`` from history + workspace.
    window_transcript — trim transcript history to the last N turns for tier-B retries.
    latest_prior_triage_result — previous turn routing from ``triage_decisions``.
    group_triage_block_would_inject — test helper wrapping ``should_inject_group_triage_block``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Final

from sevn.agent.provider_history_keys import PROVIDER_TURN_MESSAGES_KEY
from sevn.agent.transcript_replay import TranscriptRow
from sevn.agent.triager.context import (
    RegistryIndexEntry,
    RegistrySnapshot,
    SessionView,
    SkillSurfaceEntry,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.run import effective_triager_config, should_inject_group_triage_block
from sevn.config.defaults import (
    DEFAULT_PLAN_APPROVAL_ENABLED,
    INITIAL_REGISTRY_VERSION,
    TRIAGER_ENABLED_ENV_KEY,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.onboarding.first_session import bootstrap_capture_active, is_first_session_turn
from sevn.gateway.user.user_profile import get_user_profile
from sevn.gateway.util.timestamps import operator_local_date_iso
from sevn.onboarding.seed import resolve_agent_display_name
from sevn.tools.registry import ToolSet
from sevn.workspace.layout import WorkspaceLayout

_PERSONALITY_FILES = ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md")

_SEVN_PERSONA_RULE: Final[str] = (
    "You are Sevn, the operator's workspace assistant. Answer in character using "
    "[workspace personality] below (IDENTITY.md, SOUL.md, USER.md, MEMORY.md). "
    "Never name yourself as an LLM vendor or model (MiniMax, GPT, Claude, Gemini, etc.) "
    "and never say you were built by those companies."
)

_IDENTITY_TURN_RULE: Final[str] = (
    "IDENTITY_TURN: The user asks who you are, your name, role, or capabilities. "
    "Reply from IDENTITY.md and SOUL.md. Do not mention underlying models, APIs, or vendors."
)
_SUMMARY_WRAP_FMT = "<summary><content>{body}</content></summary>"


def is_triager_enabled() -> bool:
    """Return whether the gateway should invoke ``triage_turn`` (``TRIAGER_ENABLED``).

    When false, ``build_agent_run_turn`` skips the Triager LLM and uses
    :func:`passthrough_triage_result` (tier-B executor only).

    Returns:
        bool: ``False`` only when env is ``0``, ``false``, or ``off`` (case-insensitive).

    Examples:
        >>> import os
        >>> from unittest.mock import patch
        >>> with patch.dict(os.environ, {}, clear=True):
        ...     is_triager_enabled()
        True
        >>> with patch.dict(os.environ, {"TRIAGER_ENABLED": "0"}):
        ...     is_triager_enabled()
        False
    """
    raw = os.environ.get(TRIAGER_ENABLED_ENV_KEY, "1").strip().lower()
    return raw not in ("0", "false", "off", "")


def passthrough_triage_result() -> TriageResult:
    """Synthetic tier-B routing row when ``TRIAGER_ENABLED`` is false.

    Mirrors L1b downgrade shape: empty ``first_message``, no tool narrowing.

    Returns:
        TriageResult: Tier-B passthrough suitable for ``run_b_turn``.

    Examples:
        >>> r = passthrough_triage_result()
        >>> r.complexity == ComplexityTier.B
        True
        >>> r.first_message
        ''
    """
    return TriageResult.model_construct(
        intent=Intent.UNKNOWN,
        complexity=ComplexityTier.B,
        first_message="",
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.0,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        followup_anchor=None,
        permission_scope_narrowing=None,
    )


def registry_snapshot_from_tool_set(
    tool_set: ToolSet,
    *,
    workspace: WorkspaceConfig | None = None,
    content_root: Path | None = None,
) -> RegistrySnapshot:
    """Materialise a Triager catalogue slice from a session ``ToolSet``.

    Args:
        tool_set (ToolSet): Frozen registry descriptors from ``snapshot_tool_set``.
        workspace (WorkspaceConfig | None): Optional workspace for
            ``add_core_tools_to_all_context`` policy.
        content_root (Path | None): When set, loads ``TOOLS.md`` into
            ``tools_md_body`` for Triager prompts.

    Returns:
        RegistrySnapshot: Sorted index rows for ``triage_turn`` validation.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> from sevn.tools.registry import ToolSet
        >>> native = (
        ...     ToolDefinition(
        ...         name="tick",
        ...         category="session",
        ...         description="health check",
        ...         parameters={"type": "object", "properties": {}},
        ...     ),
        ... )
        >>> ts = ToolSet(3, native, (), {"zebra": "skill line"})
        >>> snap = registry_snapshot_from_tool_set(ts)
        >>> snap.tools[0].identifier
        'tick'
        >>> snap.skills[0].identifier
        'zebra'
    """
    tools = [
        RegistryIndexEntry(
            sort_name=definition.name,
            identifier=definition.name,
            display_line=f"{definition.name} - {definition.description.replace(chr(10), ' ').strip()}",
        )
        for definition in sorted(tool_set.native, key=lambda row: row.name)
    ]
    mcp_servers = [
        RegistryIndexEntry(
            sort_name=definition.name,
            identifier=definition.name,
            display_line=f"{definition.name} - {definition.description.replace(chr(10), ' ').strip()}",
        )
        for definition in sorted(tool_set.mcp, key=lambda row: row.name)
    ]
    skills = [
        RegistryIndexEntry(
            sort_name=skill_name,
            identifier=skill_name,
            display_line=f"{skill_name} - {summary.replace(chr(10), ' ').strip()}",
        )
        for skill_name, summary in sorted(tool_set.skill_descriptions.items())
    ]
    available_skills: list[SkillSurfaceEntry] = []
    for skill_name, payload in sorted(tool_set.skill_inventory.items()):
        raw_scripts = payload.get("scripts", [])
        raw_runnables = payload.get("runnables", [])
        scripts = [str(item) for item in raw_scripts] if isinstance(raw_scripts, list) else []
        runnables = [str(item) for item in raw_runnables] if isinstance(raw_runnables, list) else []
        available_skills.append(
            SkillSurfaceEntry(
                name=skill_name,
                summary=str(payload.get("summary", "")),
                scripts=scripts,
                runnables=runnables,
            ),
        )
    add_core = _add_core_tools_to_all_context(workspace)
    version = tool_set.registry_version or INITIAL_REGISTRY_VERSION
    tools_md_body: str | None = None
    if content_root is not None:
        from sevn.workspace.tools_md import read_tools_md_body

        tools_md_body = read_tools_md_body(content_root)
    return RegistrySnapshot(
        registry_version=version,
        tools=tools,
        skills=skills,
        mcp_servers=mcp_servers,
        add_core_tools_to_all_context=add_core,
        tools_md_body=tools_md_body,
        available_skills=available_skills,
    )


def session_view_from_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    channel: str,
    user_id: str,
) -> SessionView:
    """Build ``SessionView`` from gateway session metadata and routing hints.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        channel (str): Session channel key (e.g. ``telegram``).
        user_id (str): Session user id string.

    Returns:
        SessionView: Narrow session slice for Triager group-scope logic.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _ = c.execute(
        ...     "INSERT INTO gateway_sessions VALUES (?,?,?,?,?,?,?,?,?)",
        ...     ("s1", "telegram:-100", "telegram", "42", "t", "t", None, None, None),
        ... )
        >>> sv = session_view_from_session(c, "s1", channel="telegram", user_id="42")
        >>> sv.session_id
        's1'
    """
    meta = _load_session_metadata(conn, session_id)
    member_count = _resolve_chat_member_count(
        conn,
        session_id,
        channel=channel,
        user_id=user_id,
        metadata=meta,
    )
    mcp_servers = meta.get("mcp_enabled_servers")
    enabled: list[str] = []
    if isinstance(mcp_servers, list):
        enabled = [str(x) for x in mcp_servers if str(x).strip()]
    return SessionView(
        session_id=session_id,
        chat_member_count=member_count,
        mcp_enabled_servers=enabled,
    )


def tier_b_personality_instructions(
    personality_markdown: str | None,
    *,
    identity_turn: bool = False,
) -> str:
    """Build tier-B static instructions for Sevn persona (not the wire model).

    Args:
        personality_markdown (str | None): Bundle from :func:`load_workspace_personality`.
        identity_turn (bool): True for who-are-you / capability questions.

    Returns:
        str: Instruction block appended before optional BOOTSTRAP intro text.

    Examples:
        >>> out = tier_b_personality_instructions("## IDENTITY.md\\nName: Sevn", identity_turn=True)
        >>> "IDENTITY_TURN" in out and "MiniMax" in out
        True
    """
    lines = [_SEVN_PERSONA_RULE]
    if identity_turn:
        lines.append(_IDENTITY_TURN_RULE)
    if personality_markdown and personality_markdown.strip():
        lines.extend(["", "[workspace personality]", personality_markdown.strip()])
    return "\n".join(lines)


def load_workspace_personality(content_root: Path) -> tuple[str | None, int]:
    """Load ``SOUL.md`` / ``IDENTITY.md`` / ``USER.md`` / ``MEMORY.md`` for prompts.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        tuple[str | None, int]: Markdown bundle and ``personality_version`` token
            (``0`` when no narrative files exist).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "SOUL.md").write_text("voice", encoding="utf-8")
        ...     md, ver = load_workspace_personality(root)
        ...     md is not None and ver > 0
        True
    """
    parts: list[str] = []
    for name in _PERSONALITY_FILES:
        path = content_root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            parts.append(f"## {name}\n{text}")
    if not parts:
        return None, 0
    bundle = "\n\n".join(parts)
    digest = hashlib.sha256(bundle.encode("utf-8")).hexdigest()
    version = int(digest[:8], 16)
    return bundle, version


def lcm_summary_stub_for_session(conn: sqlite3.Connection, session_id: str) -> str:
    """Return the newest active LCM compaction summary for ``session_id``.

    Args:
        conn (sqlite3.Connection): Workspace SQLite handle.
        session_id (str): Gateway session id (LCM ``session_key``).

    Returns:
        str: Wrapped summary text for ``[lcm_stub]`` or empty when none.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> _c = sqlite3.connect(":memory:")
        >>> apply_migrations(_c)
        >>> lcm_summary_stub_for_session(_c, "missing")
        ''
    """
    row = conn.execute(
        """
        SELECT s.content
        FROM lcm_summaries s
        JOIN lcm_conversations c ON c.id = s.conversation_id
        WHERE c.session_key = ?
          AND s.summary_kind = 'compaction'
          AND s.subsumed_by IS NULL
        ORDER BY s.created_at DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return ""
    body = str(row[0]).strip()
    if not body:
        return ""
    return _SUMMARY_WRAP_FMT.format(body=body)


def latest_prior_triage_result(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    workspace: WorkspaceConfig,
) -> TriageResult | None:
    """Load the most recent finalised triage row for continuation fast-path replay.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        workspace (WorkspaceConfig): Parsed workspace (for ``workspace_root`` key).

    Returns:
        TriageResult | None: Previous turn routing when present.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> ws = WorkspaceConfig.minimal(workspace_root="/w")
        >>> latest_prior_triage_result(c, session_id="s", workspace=ws) is None
        True
    """
    workspace_id = str(workspace.workspace_root or "")
    row = conn.execute(
        """
        SELECT triage_result_json FROM triage_decisions
        WHERE workspace_id = ? AND session_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (workspace_id, session_id),
    ).fetchone()
    if row is None or not row[0]:
        return None
    try:
        return TriageResult.model_validate_json(str(row[0]))
    except (json.JSONDecodeError, ValueError):
        return None


def triage_context_from_session(
    conn: sqlite3.Connection,
    session_id: str,
    workspace: WorkspaceConfig,
    msg: str,
    *,
    layout: WorkspaceLayout | None = None,
    turn_id: str = "",
    channel: str | None = None,
    user_id: str | None = None,
) -> TriagePromptContext:
    """Assemble per-call Triager suffix inputs from gateway history.

    Transcript lines exclude ``msg`` when it matches the latest visible user row.
    ``inject_group_triage_block`` is left false here; ``triage_turn`` merges via
    :func:`~sevn.agent.triager.run.should_inject_group_triage_block`.
    When ``layout`` is set, loads ``personality_markdown`` and ``lcm_summary_stub``.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        workspace (WorkspaceConfig): Parsed workspace configuration.
        msg (str): Current user message text for ``current_message``.
        layout (WorkspaceLayout | None): Resolved layout for narrative files.
        turn_id (str): Turn correlation id for routing-policy ack rotation.
        channel (str | None): Session channel for first-session scope resolution.
        user_id (str | None): Session user id for first-session scope resolution.

    Returns:
        TriagePromptContext: Suffix inputs for ``triage_turn``.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> ws = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> ctx = triage_context_from_session(c, "missing", ws, "hi")
        >>> ctx.current_message
        'hi'
    """
    cfg = effective_triager_config(workspace)
    transcript = _transcript_turns(
        conn, session_id, current_message=msg, max_turns=cfg.history_turns_n
    )
    transcript_rows = _transcript_rows(
        conn, session_id, current_message=msg, max_turns=cfg.history_turns_n
    )
    personality_md: str | None = None
    personality_ver = 0
    if layout is not None:
        personality_md, personality_ver = load_workspace_personality(layout.content_root)
    lcm_stub = lcm_summary_stub_for_session(conn, session_id)
    agent_name = resolve_agent_display_name(workspace.model_dump(mode="json"))
    first_sess = is_first_session_turn(
        conn,
        session_id,
        workspace=workspace,
        channel=channel,
        user_id=user_id,
        content_root=layout.content_root if layout is not None else None,
        agent_name=agent_name,
    )
    bootstrap_active = False
    if layout is not None:
        bootstrap_active = bootstrap_capture_active(
            conn,
            session_id,
            workspace=workspace,
            content_root=layout.content_root,
            agent_name=agent_name,
            channel=channel,
            user_id=user_id,
        )
    prior_triage = latest_prior_triage_result(conn, session_id=session_id, workspace=workspace)
    operator_date = operator_local_date_iso("UTC")
    if channel and user_id:
        profile = get_user_profile(conn, channel=channel, user_id=user_id)
        operator_date = operator_local_date_iso(profile.timezone)
    return TriagePromptContext(
        current_message=msg,
        transcript_turns=transcript,
        transcript_rows=transcript_rows,
        plan_approval_enabled=_plan_approval_enabled(workspace),
        permissions_scope_narrowing_enabled=_permissions_scope_narrowing_enabled(workspace),
        inject_group_triage_block=False,
        personality_markdown=personality_md,
        personality_version=personality_ver,
        lcm_summary_stub=lcm_stub,
        is_first_session=first_sess,
        bootstrap_capture_active=bootstrap_active,
        turn_id=turn_id,
        prior_triage_result=prior_triage,
        operator_local_date=operator_date,
    )


def group_triage_block_would_inject(
    workspace: WorkspaceConfig,
    session: SessionView,
    triage_context: TriagePromptContext,
) -> bool:
    """Expose ``should_inject_group_triage_block`` for gateway tests.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.
        session (SessionView): Session view from :func:`session_view_from_session`.
        triage_context (TriagePromptContext): Base context from
            :func:`triage_context_from_session`.

    Returns:
        bool: True when the §4.1 English block belongs in the suffix.

    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> ws = parse_workspace_config({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "triager": {"group_scope": "all"},
        ... })
        >>> sv = SessionView(session_id="g", chat_member_count=3)
        >>> ctx = TriagePromptContext(current_message="hi")
        >>> group_triage_block_would_inject(ws, sv, ctx)
        True
    """
    return should_inject_group_triage_block(
        workspace=workspace,
        session=session,
        base_context=triage_context,
    )


def _add_core_tools_to_all_context(workspace: WorkspaceConfig | None) -> bool:
    """Read ``tools.add_core_tools_to_all_context`` (default true).
    Args:
        workspace (WorkspaceConfig | None): Parsed workspace or ``None``.
    Returns:
        bool: Registry segment flag for Triager prompts.
    Examples:
        >>> _add_core_tools_to_all_context(None)
        True
    """
    """Read ``tools.add_core_tools_to_all_context`` (default ``True``).
    Args:
        workspace (WorkspaceConfig | None): Parsed workspace.
    Returns:
        bool: Whether core meta tools are injected into every Triager context.
    Examples:
        >>> _add_core_tools_to_all_context(None)
        True
    """
    if workspace is None:
        return True
    tools = workspace.tools
    if not isinstance(tools, dict):
        return True
    raw = tools.get("add_core_tools_to_all_context")
    if raw is None:
        return True
    return bool(raw)


def _plan_approval_enabled(workspace: WorkspaceConfig) -> bool:
    """Mirror ``plan_approval.enabled`` into Triager suffix context.
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
    Returns:
        bool: Whether tier-C plan approval is enabled.
    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> _plan_approval_enabled(parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}))
        False
    """
    """Return ``plan_approval.enabled`` with schema default.
    Args:
        workspace (WorkspaceConfig): Parsed workspace.
    Returns:
        bool: Whether tier-C plan approval is enabled.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _plan_approval_enabled(WorkspaceConfig.minimal())
        False
    """
    section = workspace.plan_approval
    if section is None:
        return DEFAULT_PLAN_APPROVAL_ENABLED
    return bool(section.enabled)


def _permissions_scope_narrowing_enabled(workspace: WorkspaceConfig) -> bool:
    """Mirror ``permissions.scope_narrowing.enabled`` for Triager suffix.
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
    Returns:
        bool: Whether scope narrowing may appear in Triager output.
    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> _permissions_scope_narrowing_enabled(parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}))
        False
    """
    """Return ``permissions.scope_narrowing.enabled``.
    Args:
        workspace (WorkspaceConfig): Parsed workspace.
    Returns:
        bool: Whether Triager may emit ``permission_scope_narrowing``.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _permissions_scope_narrowing_enabled(WorkspaceConfig.minimal())
        False
    """
    perms = workspace.permissions
    if not isinstance(perms, dict):
        return False
    scope = perms.get("scope_narrowing")
    if not isinstance(scope, dict):
        return False
    return bool(scope.get("enabled", False))


def _load_session_metadata(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Parse ``gateway_sessions.metadata_json`` when present.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
    Returns:
        dict[str, Any]: Decoded metadata object or empty dict.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_load_session_metadata)
        True
    """
    """Load ``gateway_sessions.metadata_json`` for ``session_id``.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
    Returns:
        dict[str, Any]: Parsed metadata or empty dict.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_load_session_metadata)
        True
    """
    row = conn.execute(
        "SELECT metadata_json FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return {}
    try:
        parsed = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _latest_user_extras(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Return parsed ``extras_json`` from the newest user message row.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
    Returns:
        dict[str, Any]: Adapter routing metadata or empty dict.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_latest_user_extras)
        True
    """
    """Return ``extras_json`` from the newest user message row.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
    Returns:
        dict[str, Any]: Parsed extras or empty dict.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_latest_user_extras)
        True
    """
    row = conn.execute(
        """
        SELECT extras_json FROM gateway_messages
        WHERE session_id = ? AND role = 'user' AND kind = 'message'
        ORDER BY id DESC LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return {}
    try:
        parsed = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_chat_member_count(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    channel: str,
    user_id: str,
    metadata: dict[str, Any],
) -> int:
    """Infer group size for ``SessionView.chat_member_count``.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        channel (str): Session channel key.
        user_id (str): Session user id string.
        metadata (dict[str, Any]): Parsed session ``metadata_json``.
    Returns:
        int: Participant count (DM ⇒ 1).
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolve_chat_member_count)
        True
    """
    """Best-effort group size hint for Triager ``SessionView``.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        channel (str): Session channel key.
        user_id (str): Session user id.
        metadata (dict[str, Any]): Session metadata blob.
    Returns:
        int: Member count (minimum 1).
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolve_chat_member_count)
        True
    """
    raw = metadata.get("chat_member_count")
    if isinstance(raw, int) and raw >= 1:
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return max(1, int(raw))
    extras = _latest_user_extras(conn, session_id)
    extra_count = extras.get("chat_member_count") or extras.get("member_count")
    if isinstance(extra_count, int) and extra_count >= 1:
        return extra_count
    chat_type = extras.get("chat_type")
    if isinstance(chat_type, str) and chat_type.lower() in ("group", "supergroup", "channel"):
        return max(2, int(extra_count)) if isinstance(extra_count, int) and extra_count >= 2 else 2
    if channel == "telegram":
        chat_id = extras.get("chat_id")
        if isinstance(chat_id, int) and chat_id < 0:
            return 2
        if isinstance(chat_id, int) and user_id.isdigit() and chat_id != int(user_id):
            return 2
    return 1


def window_transcript(
    transcript_turns: list[str],
    transcript_rows: list[TranscriptRow],
    *,
    max_turns: int,
) -> tuple[list[str], list[TranscriptRow]]:
    """Trim transcript history to the last ``max_turns`` turns for tier-B retry passes.

    A failed tier-B turn re-runs the executor through summarize / full-index retry passes,
    each of which otherwise re-sends the *entire* transcript (~33 turns observed live),
    blowing the token budget ~5x. Retries fail on behaviour ("no tool called"), not missing
    context, so they only need a recent window. Each turn is one user + one assistant row,
    so the cap keeps the last ``max_turns * 2`` entries of each parallel list. Rows are
    sliced at row boundaries, so an assistant row's self-contained ``provider_turn_messages``
    (tool_use/tool_result pairs) are never split. ``max_turns <= 0`` returns the inputs
    unchanged (windowing disabled).

    Args:
        transcript_turns (list[str]): ``"role: text"`` history lines.
        transcript_rows (list[TranscriptRow]): Structured history rows.
        max_turns (int): Turn window cap (``DEFAULT_TIER_B_RETRY_HISTORY_TURNS``).

    Returns:
        tuple[list[str], list[TranscriptRow]]: Windowed ``(turns, rows)`` copies.

    Examples:
        >>> from sevn.agent.transcript_replay import TranscriptRow
        >>> turns = [f"user: m{i}" for i in range(10)]
        >>> rows = [TranscriptRow(role="user", text=f"m{i}") for i in range(10)]
        >>> wt, wr = window_transcript(turns, rows, max_turns=2)
        >>> wt
        ['user: m6', 'user: m7', 'user: m8', 'user: m9']
        >>> len(wr)
        4
        >>> window_transcript(turns, rows, max_turns=0)[0] == turns
        True
    """
    if max_turns <= 0:
        return list(transcript_turns), list(transcript_rows)
    cap = max_turns * 2
    return list(transcript_turns[-cap:]), list(transcript_rows[-cap:])


def _transcript_turns(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    current_message: str,
    max_turns: int,
) -> list[str]:
    """Load preformatted transcript lines excluding the current user line.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        current_message (str): Latest user text stored separately in suffix.
        max_turns (int): Workspace ``triager.history_turns_n`` cap.
    Returns:
        list[str]: Lines like ``user: …`` / ``assistant: …``.
    Examples:
        >>> import sqlite3
        >>> _transcript_turns(sqlite3.connect(":memory:"), "s", current_message="hi", max_turns=0)
        []
    """
    """Build ``role: text`` transcript lines for Triager context.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        current_message (str): Current user text (deduped from tail).
        max_turns (int): Maximum conversational turns to retain.
    Returns:
        list[str]: Ordered transcript lines.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_transcript_turns)
        True
    """
    if max_turns <= 0:
        return []
    cap = max_turns * 2
    rows = conn.execute(
        """
        SELECT role, kind, content FROM gateway_messages
        WHERE session_id = ? AND visible_to_llm = 1 AND kind = 'message'
          AND role IN ('user', 'assistant')
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    lines: list[str] = []
    for role, kind, content in rows:
        _ = kind
        text = str(content or "").strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
    # Strip trailing user lines already folded into ``current_message``. With a
    # single message this drops the duplicate tail; under cancel-mode burst
    # collapse ``current_message`` is the newline-merge of several pending user
    # lines, so peel each of those off the tail too (agent_turn
    # ``_pending_user_messages_text``; `specs/17-gateway.md` §2.5).
    merged_bodies = {part.strip() for part in current_message.split("\n") if part.strip()}
    merged_bodies.add(current_message.strip())
    while lines and lines[-1].startswith("user:"):
        last_body = lines[-1][len("user:") :].strip()
        if last_body in merged_bodies:
            lines = lines[:-1]
        else:
            break
    if len(lines) > cap:
        lines = lines[-cap:]
    return lines


def _parse_provider_turn_messages(extras_json: str | None) -> list[dict[str, Any]] | None:
    """Load structured provider history from one assistant ``extras_json`` blob.

    Args:
        extras_json (str | None): Raw ``gateway_messages.extras_json`` column.

    Returns:
        list[dict[str, Any]] | None: Anthropic-shaped rows when present.

    Examples:
        >>> _parse_provider_turn_messages(
        ...     '{"provider_turn_messages": [{"role": "user", "content": "hi"}]}'
        ... )[0]["role"]
        'user'
    """
    if not extras_json:
        return None
    try:
        parsed = json.loads(str(extras_json))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    raw = parsed.get(PROVIDER_TURN_MESSAGES_KEY)
    if not isinstance(raw, list) or not raw:
        return None
    rows = [row for row in raw if isinstance(row, dict)]
    return rows or None


def _transcript_rows(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    current_message: str,
    max_turns: int,
) -> list[TranscriptRow]:
    """Load structured transcript rows excluding the current user line.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        current_message (str): Latest user text stored separately in suffix.
        max_turns (int): Workspace ``triager.history_turns_n`` cap.

    Returns:
        list[TranscriptRow]: Ordered rows with optional ``provider_turn_messages``.

    Examples:
        >>> _transcript_rows(sqlite3.connect(":memory:"), "s", current_message="hi", max_turns=0)
        []
    """
    if max_turns <= 0:
        return []
    cap = max_turns * 2
    rows = conn.execute(
        """
        SELECT role, kind, content, extras_json FROM gateway_messages
        WHERE session_id = ? AND visible_to_llm = 1 AND kind = 'message'
          AND role IN ('user', 'assistant')
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    items: list[TranscriptRow] = []
    for role, kind, content, extras_json in rows:
        _ = kind
        text = str(content or "").strip()
        if not text:
            continue
        provider_messages = None
        if role == "assistant":
            provider_messages = _parse_provider_turn_messages(extras_json)
        items.append(
            TranscriptRow(
                role="user" if role == "user" else "assistant",
                text=text,
                provider_turn_messages=provider_messages,
            ),
        )
    merged_bodies = {part.strip() for part in current_message.split("\n") if part.strip()}
    merged_bodies.add(current_message.strip())
    while items and items[-1].role == "user":
        last_body = items[-1].text.strip()
        if last_body in merged_bodies:
            items = items[:-1]
        else:
            break
    if len(items) > cap:
        items = items[-cap:]
    return items


__all__ = [
    "group_triage_block_would_inject",
    "is_triager_enabled",
    "latest_prior_triage_result",
    "lcm_summary_stub_for_session",
    "load_workspace_personality",
    "passthrough_triage_result",
    "registry_snapshot_from_tool_set",
    "session_view_from_session",
    "tier_b_personality_instructions",
    "triage_context_from_session",
    "window_transcript",
]
