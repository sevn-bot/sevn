"""Declarative agent context slot order for docs, traces, and executors.

Module: sevn.agent.context_manifest
Depends: subprocess, datetime, sevn.agent.persona, sevn.prompts.tier_b

Exports:
    build_agent_context_manifest — Build the agent context manifest document.
    collect_manifest_slot_ids — Collect all slot/block ids from a manifest.
    tier_b_intro_system_prompt_builders — Build tier-B intro system prompt parts.
    tier_b_system_prompt_builders — Build tier-B full system prompt parts.

Examples:
    >>> doc = build_agent_context_manifest(git_commit="abc")
    >>> doc["schema_version"]
    1
"""

from __future__ import annotations

import subprocess  # nosec B404
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

from sevn.agent.persona import (
    load_persona_block,
    load_persona_block_intro,
    tier_b_workspace_roots_prompt,
)
from sevn.prompts import tier_b as tier_b_prompts

TRIAGER_SUFFIX_BLOCK_IDS: tuple[str, ...] = (
    "turn_context",
    "transcript",
    "lcm_stub",
    "last_routing",
    "group_triage",
    "code_orientation",
    "attachments",
    "current_message",
)

TIER_B_SYSTEM_BLOCK_IDS: tuple[str, ...] = (
    "identity_boundary",
    "identity_answer",
    "workspace_roots",
    "workspace_code_search",
    "hallucination_guard",
    "tools_vs_skills",
    "no_silent_substitution",
    "retrieval_honesty",
    "live_factual",
    "github_repo_eval",
    "persistence",
    "sessions_context",
    "architecture_context",
    "log_query_playbook",
    "log_provenance_playbook",
    "list_registry_playbook",
    "last30days_playbook",
    "codemode_playbook",
    "index_architecture",
    "brevity",
    "telegram_formatting",
    "no_preamble_echo",
    "spill_recovery",
    "tool_economy",
    "process_install",
    "browser_tool",
    "bound_skill_playbook",
    "triager_bound_mandate",
    "memorize",
    "file_link",
    "repo_access",
    "persona",
)

TIER_B_INTRO_SYSTEM_BLOCK_IDS: tuple[str, ...] = (
    "identity_boundary",
    "identity_answer",
    "hallucination_guard",
    "tools_vs_skills",
    "persistence",
    "brevity",
    "telegram_formatting",
    "no_preamble_echo",
    "memorize",
    "persona_intro",
)

_TIER_B_BUILDERS: dict[str, Callable[..., str]] = {
    "identity_boundary": tier_b_prompts.tier_b_identity_boundary_prompt,
    "identity_answer": tier_b_prompts.tier_b_identity_answer_prompt,
    "workspace_roots": tier_b_workspace_roots_prompt,
    "workspace_code_search": lambda _cr: tier_b_prompts.tier_b_workspace_code_search_prompt(),
    "hallucination_guard": lambda _cr: tier_b_prompts.tier_b_hallucination_guard_prompt(),
    "tools_vs_skills": lambda _cr: tier_b_prompts.tier_b_tools_vs_skills_prompt(),
    "no_silent_substitution": lambda _cr: tier_b_prompts.tier_b_no_silent_substitution_prompt(),
    "retrieval_honesty": lambda _cr: tier_b_prompts.tier_b_retrieval_honesty_prompt(),
    "live_factual": lambda _cr, operator_local_date="": tier_b_prompts.tier_b_live_factual_prompt(
        operator_local_date=operator_local_date,
    ),
    "github_repo_eval": lambda _cr: tier_b_prompts.tier_b_github_repo_eval_prompt(),
    "persistence": lambda _cr: tier_b_prompts.tier_b_persistence_prompt(),
    "sessions_context": tier_b_prompts.tier_b_sessions_context_prompt,
    "architecture_context": tier_b_prompts.tier_b_architecture_context_prompt,
    "log_query_playbook": lambda _cr: tier_b_prompts.tier_b_log_query_playbook_prompt(),
    "log_provenance_playbook": lambda _cr: tier_b_prompts.tier_b_log_provenance_playbook_prompt(),
    "list_registry_playbook": lambda _cr: tier_b_prompts.tier_b_list_registry_playbook_prompt(),
    "last30days_playbook": lambda _cr: tier_b_prompts.tier_b_last30days_playbook_prompt(),
    "codemode_playbook": lambda _cr: tier_b_prompts.tier_b_codemode_playbook_prompt(),
    "index_architecture": lambda _cr: tier_b_prompts.tier_b_index_architecture_prompt(),
    "brevity": lambda _cr: tier_b_prompts.tier_b_brevity_prompt(),
    "telegram_formatting": lambda _cr: tier_b_prompts.tier_b_telegram_formatting_prompt(),
    "no_preamble_echo": lambda _cr: tier_b_prompts.tier_b_no_preamble_echo_prompt(),
    "spill_recovery": lambda _cr: tier_b_prompts.tier_b_spill_recovery_prompt(),
    "tool_economy": lambda _cr: tier_b_prompts.tier_b_tool_economy_prompt(),
    "process_install": lambda _cr: tier_b_prompts.tier_b_process_install_prompt(),
    "browser_tool": lambda _cr: tier_b_prompts.tier_b_browser_tool_prompt(),
    "memorize": lambda _cr: tier_b_prompts.tier_b_memorize_prompt(),
    "file_link": lambda _cr: tier_b_prompts.tier_b_file_link_prompt(),
}


def _block(
    block_id: str,
    *,
    label: str,
    content_type: str,
    description: str = "",
    conditional: str | None = None,
) -> dict[str, Any]:
    """Build a manifest block descriptor dict.

    Args:
        block_id (str): Stable block identifier.
        label (str): Human-readable block label.
        content_type (str): Manifest content-type token.
        description (str): Optional longer description.
        conditional (str | None): Optional inclusion predicate label.

    Returns:
        dict[str, Any]: Block descriptor with ``id``, ``label``, and ``content_type``.

    Examples:
        >>> _block("foo", label="Foo", content_type="static_rules")["id"]
        'foo'
    """
    out: dict[str, Any] = {"id": block_id, "label": label, "content_type": content_type}
    if description:
        out["description"] = description
    if conditional:
        out["conditional"] = conditional
    return out


def _slot(
    order: int,
    *,
    slot_id: str,
    role: str,
    content_type: str,
    label: str,
    description: str = "",
    blocks: Sequence[dict[str, Any]] | None = None,
    segments: Sequence[dict[str, Any]] | None = None,
    conditional: str | None = None,
) -> dict[str, Any]:
    """Build a manifest slot descriptor dict.

    Args:
        order (int): Slot ordering index (1-based in manifests).
        slot_id (str): Stable slot identifier.
        role (str): Prompt role (``system``, ``user``, ``tool``, …).
        content_type (str): Manifest content-type token.
        label (str): Human-readable slot label.
        description (str): Optional longer description.
        blocks (Sequence[dict[str, Any]] | None): Nested block descriptors.
        segments (Sequence[dict[str, Any]] | None): Nested segment descriptors.
        conditional (str | None): Optional inclusion predicate label.

    Returns:
        dict[str, Any]: Slot descriptor with ``order``, ``id``, ``role``, and ``content_type``.

    Examples:
        >>> _slot(1, slot_id="s", role="system", content_type="x", label="L")["order"]
        1
    """
    out: dict[str, Any] = {
        "order": order,
        "id": slot_id,
        "role": role,
        "content_type": content_type,
        "label": label,
    }
    if description:
        out["description"] = description
    if blocks:
        out["blocks"] = list(blocks)
    if segments:
        out["segments"] = list(segments)
    if conditional:
        out["conditional"] = conditional
    return out


def tier_b_intro_system_prompt_builders(content_root: Path) -> list[str]:
    """Build ordered tier-B first-session intro ``system_prompt`` parts.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        list[str]: Prompt fragments in ``TIER_B_INTRO_SYSTEM_BLOCK_IDS`` order.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     parts = tier_b_intro_system_prompt_builders(Path(td))
        ...     isinstance(parts, list) and len(parts) == len(TIER_B_INTRO_SYSTEM_BLOCK_IDS)
        True
    """
    parts: list[str] = []
    for block_id in TIER_B_INTRO_SYSTEM_BLOCK_IDS:
        if block_id == "persona_intro":
            parts.append(load_persona_block_intro(content_root))
        else:
            parts.append(_TIER_B_BUILDERS[block_id](content_root))
    return parts


def tier_b_system_prompt_builders(
    content_root: Path,
    *,
    operator_local_date: str = "",
    log_provenance_audit: bool = False,
    codemode_on: bool = False,
    triager_bound_skill_picks: Sequence[str] = (),
    triager_bound_tool_picks: Sequence[str] = (),
    skill_descriptions: Mapping[str, str] | None = None,
    workspace: object | None = None,
) -> list[str]:
    """Build ordered tier-B full-turn ``system_prompt`` parts with conditional blocks.

    Args:
        content_root (Path): Resolved workspace content root.
        operator_local_date (str): Operator-local date string for live-factual block.
        log_provenance_audit (bool): Include log-provenance playbook when ``True``.
        codemode_on (bool): Include Code Mode playbook when ``True``.
        triager_bound_skill_picks (Sequence[str]): Triager-narrowed skill ids.
        triager_bound_tool_picks (Sequence[str]): Triager-narrowed tool ids.
        skill_descriptions (Mapping[str, str] | None): Skill summaries for persona block.
        workspace (object | None): Workspace config for repo-access block.

    Returns:
        list[str]: Prompt fragments honoring ``TIER_B_SYSTEM_BLOCK_IDS`` conditionals.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     parts = tier_b_system_prompt_builders(Path(td))
        ...     isinstance(parts, list) and len(parts) >= 1
        True
    """
    from sevn.agent.persona import tier_b_repo_access_prompt

    parts: list[str] = []
    for block_id in TIER_B_SYSTEM_BLOCK_IDS:
        if block_id == "log_provenance_playbook" and not log_provenance_audit:
            continue
        if block_id == "codemode_playbook" and not codemode_on:
            continue
        if block_id == "bound_skill_playbook" and not triager_bound_skill_picks:
            continue
        if block_id == "triager_bound_mandate" and not (
            triager_bound_tool_picks or triager_bound_skill_picks
        ):
            continue
        if block_id == "persona":
            parts.append(load_persona_block(content_root, skill_descriptions=skill_descriptions))
            continue
        if block_id == "live_factual":
            parts.append(
                tier_b_prompts.tier_b_live_factual_prompt(operator_local_date=operator_local_date),
            )
            continue
        if block_id == "bound_skill_playbook":
            parts.append(
                tier_b_prompts.tier_b_bound_skill_playbook_prompt(triager_bound_skill_picks),
            )
            continue
        if block_id == "triager_bound_mandate":
            parts.append(
                tier_b_prompts.tier_b_triager_bound_mandate_prompt(
                    triager_bound_tool_picks,
                    triager_bound_skill_picks,
                    log_provenance_audit=log_provenance_audit,
                ),
            )
            continue
        if block_id == "repo_access":
            parts.append(tier_b_repo_access_prompt(workspace, content_root))  # type: ignore[arg-type]
            continue
        parts.append(_TIER_B_BUILDERS[block_id](content_root))
    return parts


def _triager_agent() -> dict[str, Any]:
    """Return the triager agent manifest subtree.

    Returns:
        dict[str, Any]: Triager agent descriptor with ``system_prompt`` and ``user_blob`` slots.

    Examples:
        >>> _triager_agent()["id"]
        'triager'
    """
    suffix_blocks = [
        _block("turn_context", label="Turn context", content_type="turn_metadata"),
        _block("transcript", label="Transcript", content_type="transcript"),
        _block("lcm_stub", label="LCM summary stub", content_type="turn_metadata"),
        _block("last_routing", label="Last routing", content_type="turn_metadata"),
        _block(
            "group_triage",
            label="Group triage instruction",
            content_type="static_rules",
            conditional="inject_group_triage_block",
        ),
        _block(
            "code_orientation",
            label="Code orientation",
            content_type="playbooks",
            conditional="code_orientation_block present",
        ),
        _block(
            "attachments",
            label="Attachments",
            content_type="multimodal",
            conditional="attachment_hints non-empty",
        ),
        _block("current_message", label="Current message", content_type="turn_metadata"),
    ]
    return {
        "id": "triager",
        "label": "Triager",
        "uses_llm": True,
        "wire": "pydantic_ai",
        "slots": [
            _slot(
                1,
                slot_id="system_prompt",
                role="system",
                content_type="workspace_persona",
                label="System prompt",
                blocks=[
                    _block("persona", label="Persona bundle", content_type="workspace_persona"),
                    _block(
                        "json_mandate",
                        label="TriageResult JSON mandate",
                        content_type="static_rules",
                    ),
                ],
            ),
            _slot(
                2,
                slot_id="user_blob",
                role="user",
                content_type="segmented_text",
                label="User prompt (segmented)",
                segments=[
                    _block("static_prefix", label="Static prefix", content_type="static_rules"),
                    _block("registry_block", label="Registry block", content_type="registry"),
                    _block(
                        "personality_block",
                        label="Personality block",
                        content_type="personality",
                        conditional="skip_personality false",
                    ),
                    {
                        "id": "suffix",
                        "label": "Suffix segment",
                        "content_type": "segmented_text",
                        "blocks": list(suffix_blocks),
                    },
                ],
            ),
        ],
    }


def _tier_a_agent() -> dict[str, Any]:
    """Return the tier-A (non-LLM) agent manifest subtree.

    Returns:
        dict[str, Any]: Tier-A agent descriptor with a single canned-reply slot.

    Examples:
        >>> _tier_a_agent()["uses_llm"]
        False
    """
    return {
        "id": "tier_a",
        "label": "Tier A",
        "uses_llm": False,
        "wire": "gateway_only",
        "slots": [
            _slot(
                1,
                slot_id="first_message",
                role="assistant",
                content_type="canned_reply",
                label="Triager first message",
            ),
        ],
    }


def _tier_b_agent() -> dict[str, Any]:
    """Return the tier-B executor agent manifest subtree.

    Returns:
        dict[str, Any]: Tier-B agent descriptor with system, instructions, and tool slots.

    Examples:
        >>> _tier_b_agent()["variants"]["full_turn"]["system_block_ids"][0]
        'identity_boundary'
    """
    system_blocks = [
        _block(bid, label=bid.replace("_", " ").title(), content_type="playbooks")
        for bid in TIER_B_SYSTEM_BLOCK_IDS
    ]
    instruction_blocks = [
        _block("lazy_load_guidance", label="Lazy-load guidance", content_type="tools_catalog"),
        _block("error_handling_rule", label="Tool error handling", content_type="static_rules"),
        _block("tool_catalog", label="Full tool catalog", content_type="tools_catalog"),
        _block(
            "triager_narrowed_tools", label="Triager-narrowed tools", content_type="tools_catalog"
        ),
        _block(
            "triager_narrowed_skills",
            label="Triager-narrowed skills",
            content_type="skills_catalog",
        ),
        _block(
            "gateway_extra_instructions",
            label="Gateway extra instructions",
            content_type="gateway_inject",
        ),
        _block("triager_opener_note", label="Triager opener note", content_type="triager_opener"),
    ]
    return {
        "id": "tier_b",
        "label": "Tier B",
        "uses_llm": True,
        "wire": "pydantic_ai",
        "variants": {
            "full_turn": {"system_block_ids": list(TIER_B_SYSTEM_BLOCK_IDS)},
            "first_session_intro": {"system_block_ids": list(TIER_B_INTRO_SYSTEM_BLOCK_IDS)},
        },
        "slots": [
            _slot(
                1,
                slot_id="system_prompt",
                role="system",
                content_type="playbooks",
                label="System prompt",
                blocks=system_blocks,
            ),
            _slot(
                2,
                slot_id="instructions",
                role="system",
                content_type="tools_catalog",
                label="Dynamic instructions",
                blocks=instruction_blocks,
            ),
            _slot(
                3,
                slot_id="message_history",
                role="user",
                content_type="message_history",
                label="Message history",
            ),
            _slot(
                4,
                slot_id="user_prompt",
                role="user",
                content_type="multimodal",
                label="Current user prompt",
            ),
            _slot(
                5,
                slot_id="tool_schemas",
                role="tool",
                content_type="tool_schemas",
                label="Tool schemas",
            ),
        ],
    }


def _tier_c_dspy_agent() -> dict[str, Any]:
    """Return the tier-C/D dspy-wire agent manifest subtree.

    Returns:
        dict[str, Any]: Tier-C dspy agent descriptor with JSON-phase slots.

    Examples:
        >>> _tier_c_dspy_agent()["wire"]
        'json_phase'
    """
    return {
        "id": "tier_c_dspy",
        "label": "Tier C/D (dspy)",
        "uses_llm": True,
        "wire": "json_phase",
        "slots": [
            _slot(
                1, slot_id="decompose", role="user", content_type="json_phase", label="Decompose"
            ),
            _slot(
                2,
                slot_id="plan_gate",
                role="system",
                content_type="turn_metadata",
                label="Plan gate",
            ),
            _slot(
                3,
                slot_id="rlm_outer",
                role="user",
                content_type="json_phase",
                label="RLM outer loop",
            ),
            _slot(
                4,
                slot_id="synthesize",
                role="user",
                content_type="json_phase",
                label="Synthesize",
            ),
        ],
    }


def _tier_c_lambda_agent() -> dict[str, Any]:
    """Return the tier-C/D lambda-wire agent manifest subtree.

    Returns:
        dict[str, Any]: Tier-C lambda agent descriptor with macro and synthesize slots.

    Examples:
        >>> _tier_c_lambda_agent()["id"]
        'tier_c_lambda'
    """
    return {
        "id": "tier_c_lambda",
        "label": "Tier C/D (lambda)",
        "uses_llm": True,
        "wire": "json_phase",
        "slots": [
            _slot(
                1,
                slot_id="plan_gate",
                role="system",
                content_type="turn_metadata",
                label="Plan gate",
            ),
            _slot(
                2,
                slot_id="lambda_macro",
                role="user",
                content_type="json_phase",
                label="Lambda macro",
            ),
            _slot(
                3,
                slot_id="synthesize",
                role="user",
                content_type="json_phase",
                label="Synthesize",
            ),
        ],
    }


def _resolve_git_commit() -> str:
    """Resolve the current git short commit hash, or ``unknown``.

    Returns:
        str: Short ``git rev-parse`` output, or ``"unknown"`` when unavailable.

    Examples:
        >>> isinstance(_resolve_git_commit(), str)
        True
    """
    try:
        out = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def build_agent_context_manifest(*, git_commit: str | None = None) -> dict[str, Any]:
    """Build the full agent-context manifest document for docs and golden emission.

    Args:
        git_commit (str | None): Override git commit stamp; defaults to live ``git rev-parse``.

    Returns:
        dict[str, Any]: Manifest with ``schema_version``, ``generated_at``, and ``agents``.

    Examples:
        >>> doc = build_agent_context_manifest(git_commit="test")
        >>> doc["git_commit"]
        'test'
    """
    commit = git_commit if git_commit is not None else _resolve_git_commit()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "git_commit": commit,
        "agents": [
            _triager_agent(),
            _tier_a_agent(),
            _tier_b_agent(),
            _tier_c_dspy_agent(),
            _tier_c_lambda_agent(),
        ],
    }


def collect_manifest_slot_ids(manifest: dict[str, Any]) -> frozenset[str]:
    """Collect all agent, slot, block, and segment ids from a manifest.

    Args:
        manifest (dict[str, Any]): Full agent-context manifest document.

    Returns:
        frozenset[str]: Every ``id`` found on agents, slots, blocks, and segments.

    Examples:
        >>> m = build_agent_context_manifest(git_commit="x")
        >>> "triager" in collect_manifest_slot_ids(m)
        True
    """
    found: set[str] = set()

    def _walk(blocks: Sequence[dict[str, Any]] | None) -> None:
        if not blocks:
            return
        for block in blocks:
            bid = block.get("id")
            if isinstance(bid, str):
                found.add(bid)
            _walk(block.get("blocks"))
            _walk(block.get("segments"))

    for agent in manifest.get("agents", []):
        if not isinstance(agent, dict):
            continue
        aid = agent.get("id")
        if isinstance(aid, str):
            found.add(aid)
        for slot in agent.get("slots", []):
            if isinstance(slot, dict) and isinstance(slot.get("id"), str):
                found.add(slot["id"])
            _walk(slot.get("blocks") if isinstance(slot, dict) else None)
            _walk(slot.get("segments") if isinstance(slot, dict) else None)
    return frozenset(found)


__all__ = [
    "TIER_B_INTRO_SYSTEM_BLOCK_IDS",
    "TIER_B_SYSTEM_BLOCK_IDS",
    "TRIAGER_SUFFIX_BLOCK_IDS",
    "build_agent_context_manifest",
    "collect_manifest_slot_ids",
    "tier_b_intro_system_prompt_builders",
    "tier_b_system_prompt_builders",
]
