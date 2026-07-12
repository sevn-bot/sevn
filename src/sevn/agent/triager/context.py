"""Narrow facades passed into Triager assembly (`specs/13-rlm-triager.md` §2.1).

Module: sevn.agent.triager.context
Depends: pydantic, sevn.config.workspace_config, sevn.agent.triager.models

Exports:
    Classes:
        ApprovedUserTurn — scanner-approved plaintext + routing hints.
        SessionView — narrow session/read model slice.
        RegistryIndexEntry — one registry row with sort keys.
        RegistrySnapshot — tool/skill/MCP catalogue slice + versions.
        SkillSurfaceEntry — triager-facing skill inventory row with scripts/runnables.
        TriagePromptContext — per-call suffix slot fillers.

Note:
    ``Workspace`` is a module-level alias for ``WorkspaceConfig`` (kept for
    backward-compatible imports); it is not listed in ``Exports:`` because
    aliases aren't class/function definitions.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sevn.agent.transcript_replay import TranscriptRow
from sevn.agent.triager.models import FollowupAnchor, TriageResult
from sevn.config.workspace_config import WorkspaceConfig

Workspace = WorkspaceConfig


class ApprovedUserTurn(BaseModel):
    """Scanner-approved user payload (no secret attachment bytes).

    Args:
        text (str): Plaintext-only user message (`specs/13-rlm-triager.md` §2.1).

    Attributes:
        text (str): Message body.
        attachment_descriptors (list[dict[str, str]]): ``kind``, ``media_type``, ``name`` hints only.
        followup_anchor (FollowupAnchor | None): Channel pointers when applicable
            (typed discriminated union per channel; `specs/10-schema-ontology.md` §2.2).
        member_count (int): Chat participants (`specs/13-rlm-triager.md` §4.1).
        addressed_signals (dict[str, bool]): @bot / reply-to-bot hints.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    attachment_descriptors: list[dict[str, str]] = Field(default_factory=list)
    followup_anchor: FollowupAnchor | None = None
    member_count: int = Field(default=1, ge=1)
    addressed_signals: dict[str, bool] = Field(default_factory=dict)


class SessionView(BaseModel):
    """Minimal session fields Triager consumes (`specs/13-rlm-triager.md` §4.1).

    Attributes:
        session_id (str): Session key.
        chat_member_count (int): Humans in chat (DM ⇒ 1).
        mcp_enabled_servers (list[str]): Session-enabled MCP server ids/names.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    chat_member_count: int = Field(default=1, ge=1)
    mcp_enabled_servers: list[str] = Field(default_factory=list)


class RegistryIndexEntry(BaseModel):
    """One catalogue line with deterministic sort metadata (`specs/13-rlm-triager.md` §3.1).

    Attributes:
        sort_name (str): ASCII sort key (locale invariant).
        identifier (str): Tool/skill/MCP id the model must emit.
        display_line (str): Full index line embedded in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    sort_name: str
    identifier: str
    display_line: str


class SkillSurfaceEntry(BaseModel):
    """Skill menu row for triager script/runnable surfacing.

    Attributes:
        name (str): Canonical skill identifier.
        summary (str): One-line skill description.
        scripts (list[str]): Declared script paths.
        runnables (list[str]): Declared runnable ids.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str = ""
    scripts: list[str] = Field(default_factory=list)
    runnables: list[str] = Field(default_factory=list)


class RegistrySnapshot(BaseModel):
    """Materialised registry slice for Triager prompts (`specs/13-rlm-triager.md` §2.1).

    Attributes:
        tools (list[RegistryIndexEntry]): Tool index rows.
        skills (list[RegistryIndexEntry]): Skill index rows.
        mcp_servers (list[RegistryIndexEntry]): MCP catalogue rows (no schemas).
        registry_version (int): Monotonic bump for cache breakpoints.
        add_core_tools_to_all_context (bool): Mirrors workspace policy knob.
        tools_md_body (str | None): Optional ``TOOLS.md`` body copy.
    """

    model_config = ConfigDict(extra="forbid")

    tools: list[RegistryIndexEntry] = Field(default_factory=list)
    skills: list[RegistryIndexEntry] = Field(default_factory=list)
    mcp_servers: list[RegistryIndexEntry] = Field(default_factory=list)
    registry_version: int = 0
    add_core_tools_to_all_context: bool = True
    tools_md_body: str | None = None
    available_skills: list[SkillSurfaceEntry] = Field(default_factory=list)


class TriagePromptContext(BaseModel):
    """Per-call suffix fields (`specs/13-rlm-triager.md` §2.1, §4.1).

    Attributes:
        transcript_turns (list[str]): Last ``N`` turns as preformatted lines.
        transcript_rows (list[TranscriptRow]): Structured rows for cross-turn replay.
        lcm_summary_stub (str): LCM placeholder block.
        last_routing_block (str): Serialized prior routing/decision cues.
        user_language (str): BCP-47-ish label for copy planning.
        plan_approval_enabled (bool): Mirrors workspace plan gate enablement.
        permissions_scope_narrowing_enabled (bool): Whether narrowing may appear in output.
        inject_group_triage_block (bool): Append §4.1 English block before current message.
        skip_personality (bool): Omit personality segment (webhook / non-owner group, etc.).
        personality_markdown (str | None): ``SOUL/USER/MEMORY`` markdown bundle when allowed.
        personality_version (int): Version line for traces/cache.
        code_orientation_block (str): Graphify orientation prefix (`specs/28` §2.5).
        current_message (str): Fresh user line for this call.
        is_first_session (bool): First user message in this scope (BOOTSTRAP intro).
        bootstrap_capture_active (bool): Bootstrap markdown still needs capture (follow-up turns).
        turn_id (str): Correlation id for routing-policy ack rotation.
        prior_triage_result (TriageResult | None): Previous turn routing for
            continuation fast-path replay (`specs/13-rlm-triager.md`).
        attachment_hints (list[dict[str, str]]): Inbound attachment presence
            hints (``kind``, ``media_type``, ``name`` — no bytes).
        operator_local_date (str): Operator-local calendar date ``YYYY-MM-DD``
            for live-factual query year grounding.
    """

    model_config = ConfigDict(extra="forbid")

    transcript_turns: list[str] = Field(default_factory=list)
    transcript_rows: list[TranscriptRow] = Field(default_factory=list)
    lcm_summary_stub: str = ""
    last_routing_block: str = ""
    user_language: str = "en"
    plan_approval_enabled: bool = False
    permissions_scope_narrowing_enabled: bool = False
    inject_group_triage_block: bool = False
    skip_personality: bool = False
    personality_markdown: str | None = None
    personality_version: int = 0
    code_orientation_block: str = ""
    current_message: str
    is_first_session: bool = False
    bootstrap_capture_active: bool = False
    turn_id: str = ""
    prior_triage_result: TriageResult | None = None
    attachment_hints: list[dict[str, str]] = Field(default_factory=list)
    operator_local_date: str = ""
