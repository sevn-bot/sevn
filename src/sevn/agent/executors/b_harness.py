"""Tier-B Pydantic AI harness (`specs/14-executor-tier-b.md` §2, §4).

``run_b_turn`` is the awaitable gateway hook after ``TriageResult.first_message`` for
``complexity == B``. It keeps Triager-chosen **description-only** scaffolding in the static
instructions while lazily attaching full JSON tool schemas after ``load_tool`` (§3.3).

Module: sevn.agent.executors.b_harness
Depends: pydantic_ai, sevn.agent.adapters.*, sevn.tools.*

Exports:
    build_tier_b_capabilities — assemble tier-B ``Agent`` capabilities (W5).
    run_b_turn — tier-B executor entrypoint.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(run_b_turn)
    True
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from time import time_ns
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pydantic_ai.capabilities.abstract import AbstractCapability
    from pydantic_ai.capabilities.hooks import Hooks
    from pydantic_ai.toolsets import AbstractToolset

    from sevn.gateway.turn_media import TurnMediaItem

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai._agent_graph import ModelRequestNode
from pydantic_ai.capabilities import PrepareTools
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.usage import UsageLimits

from sevn.agent.adapters.native_model import (
    default_native_model_context,
    resolve_pydantic_model_for_slot,
)
from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration, register_pydantic_tools
from sevn.agent.adapters.tier_b_capabilities import (
    build_web_thinking_extra_capabilities,
    registry_tool_names_owned_by_web_capabilities,
    resolve_web_egress_domain_policy,
)
from sevn.agent.adapters.tier_b_codemode import (
    build_codemode_capability,
    compute_codemode_eligible_names,
)
from sevn.agent.adapters.tier_b_hooks import TierBHookConfig, build_tier_b_hooks
from sevn.agent.adapters.tier_b_model import (
    TriagerBoundToolChoiceContext,
    _display_text_from_model_response,
    build_tier_b_function_model,
    pydantic_messages_to_anthropic_messages,
)
from sevn.agent.adapters.tier_b_multimodal import (
    UserPromptContent,
    build_tier_b_user_prompt,
    resolve_tier_b_modality_support,
    resolve_turn_media_items,
)
from sevn.agent.adapters.tier_b_overflow import build_overflow_capability
from sevn.agent.adapters.tier_b_skill_capabilities import build_tier_b_skill_capabilities
from sevn.agent.adapters.tier_b_tools import (
    _NEVER_LAZY_NAMES,
    bound_file_search_tools,
    eager_hydrate_tool_names,
    meta_tool_name_frozenset,
    prepare_lazy_tool_definitions,
)
from sevn.agent.adapters.tier_b_toolset import (
    SevnRegistryToolset,
    bound_tools_only_first_round,
)
from sevn.agent.adapters.tool_part_filter import (
    DIAGNOSTIC_RECOVERY_TOOLS,
    FILE_PIPELINE_TOOL_IDS,
    MutableToolAllowlist,
)
from sevn.agent.executors.b_types import (
    EXECUTOR_TIMEOUT_CANCEL_DETAIL,
    TIER_B_ROUND_BUDGET_TEMPLATE,
    BTierDeps,
    BTurnOutcome,
    ChannelPayload,
    EscalationRequest,
    ResolvedTierBModel,
    SessionHandle,
    SteerInject,
)
from sevn.agent.grounding import (
    append_output_truncation_notice,
    apply_file_delivery_grounding_guard,
    apply_live_factual_grounding_guard,
    claims_bound_tool_unavailable,
    last_model_stop_reason,
    steer_for_direct_tool_call,
    steer_for_opener_only,
    steer_for_promised_action,
    steer_for_triager_bound_tools_unused,
    tools_attempted_from_call_counts,
    triager_bound_tools_satisfied,
)
from sevn.agent.openers import BARE_OPENERS, MOTION_PROMISE_MARKERS, strip_opener_echo
from sevn.agent.persona import (
    build_tier_b_intro_prompt_parts,
)
from sevn.agent.tracing.otel_pipeline import instrumentation_capability
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.agent.tracing.trace_event_bridge import attach_turn_trace_context
from sevn.agent.transcript_replay import (
    TranscriptRow,
    build_cross_turn_message_history,
    sanitize_provider_turn_messages_for_storage,
    serialize_provider_turn_messages,
    slim_transcript_for_log_provenance,
)
from sevn.agent.triager.context import Workspace
from sevn.agent.triager.models import ComplexityTier, TriageResult
from sevn.agent.triager.routing_policy import (
    is_file_search_intent_message,
    is_identity_or_capability_message,
    is_log_provenance_intent_message,
)
from sevn.config.defaults import TIER_B_TOOL_MAX_RETRIES
from sevn.config.llm_params import resolve_effective_max_output_tokens
from sevn.config.model_resolution import (
    ModelSlot,
    codemode_enabled,
    codemode_max_retries,
    codemode_resource_limits,
    native_model_enabled,
)
from sevn.config.sections.providers import providers_section_dict
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import (
    tier_b_count_planning,
    tier_b_rounds,
)
from sevn.data.skills_index import read_skills_index
from sevn.prompts.fallbacks import format_tier_b_operator_failure_report
from sevn.skills.manager import SkillsManager
from sevn.tools.base import ToolDefinition, ToolExecutor
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.meta_escalation import request_escalation_pydantic_tool
from sevn.tools.meta_loaders import META_TOOL_NAMES
from sevn.tools.permissions import apply_permission_scope_narrowing
from sevn.tools.registry import ToolSet

StreamingSink = Callable[[str], Awaitable[None]]
"""Callback for streamed tier-B answer deltas (`PROBLEMS.md` Priority 2 Mode 1).

The harness invokes the sink with the *accumulated* answer text (not per-token
delta) so adapters can use the value as an in-place replacement for the
placeholder message. Sink failures are caught and logged — they never abort
the executor.
"""


def _full_tool_catalog_lines(definitions: Sequence[ToolDefinition]) -> list[str]:
    """Render the complete enabled-tool catalog (name + one-line description).

    Lists every enabled, non-meta registry tool so the executor's self-knowledge of
    its toolset is always complete and authoritative — it cannot under-report (then
    anchor on that stale list) and falsely claim a bound tool is unavailable
    (`sevn.agent.grounding.claims_bound_tool_unavailable`, the W2 confabulation that
    misrouted a bound ``serp`` call). Awareness only: JSON ``parameters`` schemas stay
    lazy/eager-hydrated. Meta tools (``META_TOOL_NAMES``) are excluded to mirror the
    ``list_registry`` tool output exactly.

    Args:
        definitions (Sequence[ToolDefinition]): Live registry definitions (``tool_executor``).

    Returns:
        list[str]: A header line followed by one ``- name: description`` row per tool,
        sorted by name. Identical across turns at a given ``registry_version``.

    Examples:
        >>> defs = [
        ...     ToolDefinition(name="serp", category="web", description="search", parameters={}),
        ...     ToolDefinition(name="load_tool", category="meta", description="load", parameters={}),
        ... ]
        >>> lines = _full_tool_catalog_lines(defs)
        >>> "- serp: search" in lines
        True
        >>> any(line.startswith("- load_tool") for line in lines)  # meta excluded
        False
    """
    rows = sorted(
        (d.name, d.description) for d in definitions if d.enabled and d.name not in META_TOOL_NAMES
    )
    lines = [
        "Full tool catalog — your COMPLETE callable toolset. This list is "
        "authoritative over anything said earlier in the conversation about which "
        "tools exist; never claim one of these is unavailable. Schemas for the tools "
        "selected this turn are already attached; call load_tool(name) to attach a "
        "schema for any other tool before using it.",
    ]
    lines.extend(f"- {name}: {desc}" for name, desc in rows)
    return lines


def _description_only_instructions(
    registration: PydanticToolRegistration,
    *,
    catalog_lines: Sequence[str] | None = None,
) -> str:
    """Assemble static instructions without embedding JSON ``parameters`` blobs.

    Omits the "Lazy-load … load_tool(name)" line when all non-always-on tools in the
    registration are eagerly hydrated (i.e. ``eager_hydrate_tool_names`` returned the
    full candidate set), so weak models are not told to call ``load_tool`` on tools that
    already have full schemas.

    When ``catalog_lines`` is supplied the full enabled-tool catalog replaces the
    per-turn narrowed tool list and a "Selected for this turn" pointer names the bound
    subset whose schemas are already attached. The catalog is stable per
    ``registry_version`` (cache-friendly); only the pointer varies per turn.

    Args:
        registration (PydanticToolRegistration): Narrowed Triager-chosen tool/skill rows.
        catalog_lines (Sequence[str] | None): Full-catalog block from
            ``_full_tool_catalog_lines``. When ``None`` the legacy narrowed tool list
            is emitted (fallback for callers without a live registry).

    Returns:
        str: Multi-line instruction text describing available tools and skills.

    Examples:
        >>> from sevn.agent.adapters.pydantic_adapter import PydanticToolRegistration
        >>> # Small set (1 tool) — all eager; lazy-load line is omitted.
        >>> reg_small = PydanticToolRegistration(
        ...     tool_names=("alpha",),
        ...     tool_descriptions={"alpha": "do alpha"},
        ...     skill_names=(),
        ...     skill_descriptions={},
        ... )
        >>> "load_tool" in _description_only_instructions(reg_small)
        False
        >>> # Large set (8 tools) — not all eager; lazy-load line is present.
        >>> reg_big = PydanticToolRegistration(
        ...     tool_names=tuple(f"tool_{i}" for i in range(8)),
        ...     tool_descriptions={},
        ...     skill_names=(),
        ...     skill_descriptions={},
        ... )
        >>> "load_tool" in _description_only_instructions(reg_big)
        True
        >>> # With a catalog the full list is emitted plus a per-turn pointer.
        >>> out = _description_only_instructions(
        ...     reg_small, catalog_lines=["Full tool catalog — ...", "- read: read a file"]
        ... )
        >>> "- read: read a file" in out
        True
        >>> "Selected for this turn (schemas attached): alpha" in out
        True
    """
    eagerly_hydrated = eager_hydrate_tool_names(registration)
    # Any non-always-on tool NOT in the eager set still needs lazy loading.
    has_lazy_tools = bool(frozenset(registration.tool_names) - _NEVER_LAZY_NAMES - eagerly_hydrated)

    lines: list[str] = []
    if has_lazy_tools:
        lines.append(
            "Lazy-load full JSON tool schemas with load_tool(name) and skill menus"
            " with load_skill(name).",
        )
    lines.append(
        "If a tool returns an envelope with ok=false, surface the failure to the user in "
        "one short line (include the tool name and the error message) before suggesting a "
        "next step. Do not silently retry, fabricate the result, or claim success."
    )
    if catalog_lines:
        lines.extend(catalog_lines)
        selected = ", ".join(registration.tool_names) or "(none)"
        lines.append(f"Selected for this turn (schemas attached): {selected}")
    else:
        lines.append("Triager-narrowed tool descriptions:")
        for name in registration.tool_names:
            desc = registration.tool_descriptions.get(name, "")
            lines.append(f"- {name}: {desc}")
    if registration.skill_names:
        lines.append("Triager-narrowed skill descriptions:")
        for name in registration.skill_names:
            desc = registration.skill_descriptions.get(name, "")
            lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


_EXECUTION_INTENT_TOOLS: frozenset[str] = frozenset(
    {
        "run_skill_script",
        "send_file",
        "write",
        "get_page_content",
        "web_fetch",
        "edit",
    }
)

# Meta loaders always available; they do not count as registry-bound must-satisfy picks (W2 / D2).
_TRIAGER_META_ONLY_BOUND_TOOLS: frozenset[str] = frozenset(
    {
        "load_tool",
        "load_skill",
        "list_registry",
        "request_escalation",
        "run_skill_script",
        "run_skill_runnable",
        "send_file",
    },
)


def _triager_bound_registry_tools(tool_picks: Sequence[str]) -> frozenset[str]:
    """Return triager-bound registry tools excluding meta-only loaders (W2 / D2).

    Args:
        tool_picks (Sequence[str]): ``TriageResult.tools`` for this turn.

    Returns:
        frozenset[str]: Bound registry tool names that require a successful call.

    Examples:
        >>> sorted(_triager_bound_registry_tools(["search_in_file", "load_tool"]))
        ['search_in_file']
        >>> _triager_bound_registry_tools(["load_tool", "list_registry"])
        frozenset()
    """
    return frozenset(tool_picks) - _TRIAGER_META_ONLY_BOUND_TOOLS


_SHELL_BYPASS_TOOLS: frozenset[str] = frozenset({"terminal_run", "sandbox_exec"})


def _bound_tools_bypassed_via_shell(
    *,
    triager_bound_tool_picks: Sequence[str],
    successful_tools_called: frozenset[str],
    incoming_text: str,
) -> bool:
    """Return True when shell tools succeeded but bound file/search tools did not (W3 / 816cba).

    Args:
        triager_bound_tool_picks (Sequence[str]): Triager-bound registry tools this turn.
        successful_tools_called (frozenset[str]): Tools that returned ``ok=true``.
        incoming_text (str): Current user message.

    Returns:
        bool: ``True`` when file/search tools were bound, none succeeded, a shell tool
        succeeded, and the user message matches file-search intent.

    Examples:
        >>> _bound_tools_bypassed_via_shell(
        ...     triager_bound_tool_picks=["search_in_file"],
        ...     successful_tools_called=frozenset({"terminal_run"}),
        ...     incoming_text="search markdown for temperature",
        ... )
        True
        >>> _bound_tools_bypassed_via_shell(
        ...     triager_bound_tool_picks=["search_in_file"],
        ...     successful_tools_called=frozenset({"search_in_file"}),
        ...     incoming_text="search markdown for temperature",
        ... )
        False
    """
    bound_file_search = bound_file_search_tools(frozenset(triager_bound_tool_picks))
    if not bound_file_search:
        return False
    if bound_file_search & successful_tools_called:
        return False
    if not (_SHELL_BYPASS_TOOLS & successful_tools_called):
        return False
    return is_file_search_intent_message(incoming_text)


def _strip_opener_echo(text: str, opener: str) -> str:
    """Remove a leading echo of the triager opener from tier-B output.

    Delegates to :func:`sevn.agent.openers.strip_opener_echo` so the harness and
    gateway share one algorithm.

    Args:
        text (str): Tier-B assembled output text.
        opener (str): The triager ``first_message`` already shown to the user.

    Returns:
        str: ``text`` with a leading echo of ``opener`` removed.

    Examples:
        >>> _strip_opener_echo("On it — checking.\\n\\nThe answer.", "On it — checking.")
        'The answer.'
        >>> _strip_opener_echo("The answer.", "On it — checking.")
        'The answer.'
    """
    return strip_opener_echo(text, opener)


def _is_opener_only_output(text: str, opener: str) -> bool:
    """Whether tier-B output carries no substantive answer beyond an opener/ack.

    Treats a final body as *empty of content* when, after removing any echo of the
    triager ``opener``, what remains is blank, equals the opener, or is a short
    opener-like filler line ('On it…', 'Here you go:', 'Pulling the list.') with no
    body. Used to reclassify an opener-only tier-B turn as a no-answer outcome so the
    gateway runs its widened-retry / typed-fallback path instead of shipping the bare
    ack (``specs/14-executor-tier-b.md`` §2.7; ``PROBLEMS.md`` P2).

    Conservative by design — a reply that *starts* like an opener but then contains
    real content is NOT flagged, because the opener-stripped remainder is non-empty.

    Args:
        text (str): Assembled tier-B output text (``str(result.output)``).
        opener (str): Triager ``first_message`` already delivered to the user.

    Returns:
        bool: ``True`` when the reply is opener-only / echo-only / empty.

    Examples:
        >>> _is_opener_only_output("On it — let me pull the list.", "On it — checking.")
        True
        >>> _is_opener_only_output("Here you go — the full list:", "On it — checking.")
        True
        >>> _is_opener_only_output("- read\\n- glob\\n- list_registry", "On it — checking.")
        False
        >>> _is_opener_only_output("OK — the workspace has 3 folders: a, b, c.", "On it.")
        False
        >>> _is_opener_only_output("", "On it — checking.")
        True
        >>> _is_opener_only_output("On it — checking.", "On it — checking.")
        True
    """
    if not text.strip():
        return True
    remainder = _strip_opener_echo(text, opener).strip()
    if not remainder:
        return True
    # Multi-line output is never opener-only: a list/answer was rendered on
    # subsequent lines even if line one reads like an opener.
    if "\n" in remainder.strip():
        return False
    normalized = " ".join(remainder.lower().split())
    if not any(normalized.startswith(prefix) for prefix in BARE_OPENERS):
        return False
    # The remainder opens with filler. It is opener-ONLY only when it is a bare
    # promise to fetch/produce the answer with no data after it. Two shapes:
    #   (a) ends on a colon / dash with nothing after it ("Here you go — the list:")
    #       — the list never followed;
    #   (b) the whole clause is a promise verb phrase (pull / fetch / get / check /
    #       re-pull the …) and no informative content survives stripping it.
    # A real short answer ("OK — the workspace has 3 folders: a, b, c.") carries
    # data tokens (commas, digits, words past the colon) and is NOT flagged.
    trimmed = normalized.rstrip(" \t.,;!?")
    if trimmed.endswith((":", "—", "-")):
        return True
    # Content past a colon (list rendered inline) clears the flag.
    _, sep, after_colon = normalized.partition(":")
    if sep and after_colon.strip(" \t.,—-;!?"):
        return False
    # Short single-line remainder that opens with a bare-opener prefix and carries
    # no inline data is filler (structural: empty-after-strip already handled above).
    # Length bound avoids misclassifying a substantive paragraph that merely
    # starts like an opener.
    if len(normalized) > 90:
        return False
    _FETCH_VERBS = ("pull", "re-pull", "fetch", "get the", "check", "look", "load", "retriev")
    return any(verb in normalized for verb in _FETCH_VERBS)


def _echoes_triager_filler(text: str, opener: str) -> bool:
    """Whether tier-B output merely restates the triager opener with no new work.

    Args:
        text (str): Assembled tier-B output text.
        opener (str): Triager ``first_message`` already delivered to the user.

    Returns:
        bool: ``True`` when the body is a near-verbatim echo of the opener.

    Examples:
        >>> _echoes_triager_filler(
        ...     "Picking it back up — re-rendering that PDF now.",
        ...     "On it — I'll render the PDF.",
        ... )
        False
        >>> _echoes_triager_filler("On it — checking.", "On it — checking.")
        True
    """
    body = " ".join((text or "").strip().lower().split())
    op = " ".join((opener or "").strip().lower().split())
    if not body:
        return True
    if not op:
        return False
    if body == op:
        return True
    if body.startswith(op) and len(body) <= len(op) + 24:
        return True
    return bool(op in body and len(body) <= len(op) + 40)


def _is_execution_filler_completion(
    *,
    rounds_used: int,
    text: str,
    opener: str,
    triage_tools: Sequence[str],
) -> bool:
    """Whether a zero-round completion is filler for an execution-heavy turn (P8).

    Args:
        rounds_used (int): Provider rounds consumed this turn.
        text (str): Assembled tier-B output text.
        opener (str): Triager ``first_message``.
        triage_tools (Sequence[str]): Triager-bound tool names.

    Returns:
        bool: ``True`` when filler must not be the terminal answer.

    Examples:
        >>> _is_execution_filler_completion(
        ...     rounds_used=0,
        ...     text="On it — I'll run the full pipeline.",
        ...     opener="On it — I'll run the full pipeline.",
        ...     triage_tools=("run_skill_script", "send_file"),
        ... )
        True
    """
    if rounds_used != 0:
        return False
    if not set(triage_tools) & _EXECUTION_INTENT_TOOLS:
        return False
    return _is_opener_only_output(text, opener) or _echoes_triager_filler(text, opener)


def _is_promised_but_idle(
    *,
    rounds_used: int,
    text: str,
    opener: str,
) -> bool:
    """Whether a zero-round finalize is a contentless motion-promise (P4).

    Detects the "all talk, no walk" failure: the triager already sent an early
    ack and the tier-B executor finalizes with *another* contentless promise to
    act ("On it — rendering the markdown to PDF now.", "Right. Talking is done.
    Doing.", "Fair. Executing now.") while running **zero** state-changing tools.
    Callers must gate on ``rounds_used == 0`` and on the absence of
    tool-produced ``channel_payloads`` before treating a hit as a failed turn.

    Conservative by design — a reply is only flagged when, after stripping any
    echo of the triager ``opener``, the surviving body is *short* (a single
    promise clause) and is dominated by a motion-promise marker. Multi-line
    output, or any body carrying real data past the promise, is never flagged.

    Args:
        rounds_used (int): Provider tool-call rounds consumed this turn.
        text (str): Assembled tier-B output text (``str(result.output)``).
        opener (str): Triager ``first_message`` already delivered to the user.

    Returns:
        bool: ``True`` when the reply is a bare promise-to-act with no work done.

    Examples:
        >>> _is_promised_but_idle(
        ...     rounds_used=0,
        ...     text="On it — rendering the markdown to PDF now.",
        ...     opener="On it — checking.",
        ... )
        True
        >>> _is_promised_but_idle(
        ...     rounds_used=0,
        ...     text="Right. Talking is done. Doing.",
        ...     opener="On it — checking.",
        ... )
        True
        >>> _is_promised_but_idle(
        ...     rounds_used=0,
        ...     text="Fair. Executing now.",
        ...     opener="On it — checking.",
        ... )
        True
        >>> # A turn that actually ran a tool is never flagged.
        >>> _is_promised_but_idle(
        ...     rounds_used=1,
        ...     text="Executing now.",
        ...     opener="On it.",
        ... )
        False
        >>> # A real short answer is never flagged.
        >>> _is_promised_but_idle(
        ...     rounds_used=0,
        ...     text="Done — the PDF is 3 pages and lives at out/report.pdf.",
        ...     opener="On it.",
        ... )
        False
    """
    if rounds_used != 0:
        return False
    remainder = _strip_opener_echo(text, opener).strip()
    if not remainder:
        # An empty / pure-echo body is already handled by the opener-only guard;
        # P4 owns the case where a *new* promise clause survives stripping.
        return False
    # Multi-line output rendered an answer/list on later lines — not a bare promise.
    if "\n" in remainder:
        return False
    normalized = " ".join(remainder.lower().split())
    # Bound length so a substantive single-line answer that mentions a promise word
    # is not misclassified. A genuine motion-promise is a short clause.
    if len(normalized) > 90:
        return False
    if not any(marker in normalized for marker in MOTION_PROMISE_MARKERS):
        return False
    # Content rendered inline past a colon clears the flag (e.g. "Doing: a, b, c").
    _, sep, after_colon = normalized.partition(":")
    if sep and after_colon.strip(" \t.,—-;!?"):
        return False
    # Digits anywhere signal real data (counts, paths with line numbers) — not a
    # bare promise.
    return not any(ch.isdigit() for ch in normalized)


def _outcome_tool_fields(
    deps: BTierDeps,
) -> dict[str, bool | str | None | frozenset[str]]:
    """Shared per-turn tool-state fields for :class:`BTurnOutcome`.

    Args:
        deps (BTierDeps): Per-run dependency bag.

    Returns:
        dict[str, object]: Keyword arguments for ``BTurnOutcome`` tool tracking.

    Examples:
        >>> fields = _outcome_tool_fields(
        ...     BTierDeps(
        ...         tool_executor=None,  # type: ignore[arg-type]
        ...         tool_context_template=None,  # type: ignore[arg-type]
        ...         workspace_path=Path("/tmp"),
        ...         registry_version=1,
        ...     )
        ... )
        >>> "had_tool_failures" in fields
        True
    """
    return {
        "had_tool_failures": deps.tool_failure_count > 0,
        "last_tool_failure_name": deps.last_tool_failure_name,
        "successful_tools_called": frozenset(deps.successful_tools_called),
        "tools_attempted": tools_attempted_from_call_counts(deps.tool_call_counts),
        "codemode_bound_tools_called": frozenset(deps.codemode_bound_tools_called),
        "grounding_tools_called": frozenset(deps.grounding_tools_called),
    }


def _resolve_skill_descriptions(
    *,
    allowed: Sequence[str],
    registry: Mapping[str, str],
) -> Mapping[str, str]:
    """Pick the persona-block skill descriptions from the triager allowlist.

    Bridges the triager's narrowed ``TriageResult.skills`` to the workspace-
    authoritative ``skills/INDEX.md`` (``PROBLEMS.md`` §Priority 1, V1 finding).
    When the triager narrowed and the index has matching rows that are *also*
    available in the executor's ``tool_set``, the persona block renders only
    those — that's the change that drops the tool-call count for capability
    questions.

    Falls back to the full ``tool_set.skill_descriptions`` when:

    - The triager didn't narrow (``allowed`` is empty), or
    - The index/registry intersection is empty (defensive — keep the executor
      functional even if the index is stale).

    Args:
        allowed (Sequence[str]): ``TriageResult.skills`` after the triager's
            ``_filter_identifiers`` pass (already constrained to registry-known
            names).
        registry (Mapping[str, str]): ``tool_set.skill_descriptions`` — the
            full registered set for this turn.

    Returns:
        Mapping[str, str]: ``{name: description}`` to feed
        :func:`sevn.agent.persona.load_persona_block`.

    Examples:
        Empty allowlist falls back to the full registry.

        >>> _resolve_skill_descriptions(allowed=[], registry={"a": "x"})
        {'a': 'x'}

        Allowlist names absent from the shipped index fall back to the registry
        (defensive — keeps the executor functional when the index is stale).

        >>> _resolve_skill_descriptions(allowed=["a"], registry={"a": "x"})
        {'a': 'x'}

        Allowlist that overlaps the index narrows the registry view.

        >>> out = _resolve_skill_descriptions(
        ...     allowed=["graphify"],
        ...     registry={"graphify": "fallback", "mycode": "other"},
        ... )
        >>> list(out) == ["graphify"]
        True
    """
    if not allowed:
        return registry
    available = set(registry)
    narrow = read_skills_index(names=allowed)
    narrowed = {k: v for k, v in narrow.items() if k in available}
    if not narrowed:
        return registry
    return narrowed


def _is_tool_description_leak(
    text: str,
    tool_descriptions: Mapping[str, str],
) -> bool:
    """Return True when ``text`` is a near-verbatim copy of a registered tool description.

    F4 (2026-06-03 session): a zero-tool tier-B round produced
    ``'On it — checking logs now.Read the log file used for debugging the request.
    Default is logs/gateway.log.'`` — the model concatenated its own opener with the
    ``log_query`` tool description instead of calling the tool.  This guard detects
    that class of leak and reclassifies the output as a failed turn so the gateway
    can run its widened-retry / no-answer path.

    Detection strategy: for each registered tool description (≥ 20 chars), check
    whether the normalised description appears verbatim within the normalised output
    text.  Two check shapes are applied:

    1. **Whole-text match**: the entire output (normalised) *is* the description.
    2. **Substring match**: the description appears as a contiguous substring within
       the output — catching "opener_sentence.description" concatenations.

    Short descriptions (< 20 chars) are skipped to avoid false positives on generic
    words ("do x").

    Only meaningful when ``rounds_used == 0`` (no tool calls occurred); callers should
    gate on that before calling this function.

    Args:
        text (str): Assembled tier-B output text.
        tool_descriptions (Mapping[str, str]): ``{name: one-line description}`` for
            the tools available on this turn.

    Returns:
        bool: ``True`` when the text is dominated by a tool description.

    Examples:
        >>> descs = {"log_query": "Read the log file. Default is logs/gateway.log."}
        >>> _is_tool_description_leak(
        ...     "On it.Read the log file. Default is logs/gateway.log.", descs
        ... )
        True
        >>> _is_tool_description_leak(
        ...     "Read the log file. Default is logs/gateway.log.", descs
        ... )
        True
        >>> _is_tool_description_leak("The answer is 42.", descs)
        False
        >>> _is_tool_description_leak("", descs)
        False
    """
    body = text.strip()
    if not body:
        return False
    normed_body = " ".join(body.lower().split())
    for desc in tool_descriptions.values():
        if len(desc) < 20:
            continue
        normed_desc = " ".join(desc.lower().split())
        if normed_desc in normed_body:
            return True
    return False


async def _emit(trace: TraceSink | None, event: TraceEvent) -> None:
    """Emit a trace event when a sink is wired (no-op otherwise).

    Args:
        trace (TraceSink | None): Optional structured trace sink.
        event (TraceEvent): Event payload to emit.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_emit(None, None))  # type: ignore[arg-type]
    """
    if trace is None:
        return
    await trace.emit(event)


async def _consume_model_request_stream(
    node: ModelRequestNode[BTierDeps, Any],
    agent_run_ctx: Any,
    *,
    sink: StreamingSink,
    debounce_s: float,
    session_id: str,
    turn_id: str,
    gateway_stream_debug: bool = False,
) -> None:
    """Drain a ``ModelRequestNode`` text stream before ``agent_run`` advances.

    pydantic-ai requires each ``node.stream()`` generator to be fully consumed
    before the outer ``async for node in agent_run`` loop may advance; partial
    consumption on follow-up rounds triggers ``You must finish streaming before
    calling run()`` (D10 / W7).

    Args:
        node (ModelRequestNode): Model request node whose answer text is streaming.
        agent_run_ctx (Any): ``agent_run.ctx`` passed to ``node.stream(ctx)``.
        sink (StreamingSink): Progressive answer callback (accumulated text).
        debounce_s (float): ``stream_text(debounce_by=...)`` cadence in seconds.
        session_id (str): Session id for sink-failure logs.
        turn_id (str): Turn id for sink-failure logs.
        gateway_stream_debug (bool): When ``True``, emit ``tier_b.stream_chunk`` DEBUG
            events (``logging.gateway_stream_debug``; default off — finalizer+adapter
            are canonical).

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_consume_model_request_stream)
        True
    """
    from sevn.logging.structured import debug_event, preview

    async with node.stream(agent_run_ctx) as model_stream:
        async for accumulated in model_stream.stream_text(
            delta=False,
            debounce_by=debounce_s,
        ):
            try:
                await sink(accumulated)
                if gateway_stream_debug:
                    debug_event(
                        "tier_b.stream_chunk",
                        session_id=session_id,
                        turn_id=turn_id,
                        text_len=len(accumulated),
                        preview=preview(accumulated),
                    )
            except Exception:
                logger.exception(
                    "b_harness.streaming_sink_failed session_id={} turn_id={}",
                    session_id,
                    turn_id,
                )


def build_tier_b_capabilities(
    *,
    hooks: Hooks,
    extra: Sequence[AbstractCapability[BTierDeps]] | None = None,
    codemode_on: bool = False,
    codemode_limits: Mapping[str, float | int] | None = None,
    codemode_max_retries: int | None = None,
    overflow_on: bool = True,
) -> list[AbstractCapability[BTierDeps]]:
    """Assemble tier-B agent capabilities (W5 merge-conflict mitigation).

    Later waves (W7 web/thinking, W8 ``CodeMode``) extend this helper instead of
    editing the ``Agent(...)`` call directly. W1 ``Instrumentation`` is always included.

    Args:
        hooks (Hooks): Tier-B lifecycle hooks (steer, grounding, permission, budget, approval).
        extra (Sequence[AbstractCapability[BTierDeps]] | None): Optional capabilities appended
            after the core bundle (e.g. W7 ``WebSearch`` / ``Thinking``).
        codemode_on (bool): When ``True``, append triager-scoped ``CodeMode`` (W8).
        codemode_limits (Mapping[str, float | int] | None): Monty sandbox ``ResourceLimits``
            for ``CodeMode`` (duration/memory/allocations); ``None`` uses defaults.
        codemode_max_retries (int | None): ``run_code`` retry budget; ``None`` uses defaults.
        overflow_on (bool): When ``True``, append ``OverflowingToolOutput`` (D6).

    Returns:
        list[AbstractCapability[BTierDeps]]: Capability list for ``Agent(capabilities=...)``.

    Examples:
        >>> from pydantic_ai.capabilities.hooks import Hooks
        >>> caps = build_tier_b_capabilities(hooks=Hooks())
        >>> len(caps) >= 3
        True
        >>> caps[0].__class__.__name__
        'Instrumentation'
    """
    capabilities: list[AbstractCapability[BTierDeps]] = [
        cast("AbstractCapability[BTierDeps]", instrumentation_capability()),
        cast("AbstractCapability[BTierDeps]", hooks),
        PrepareTools(prepare_lazy_tool_definitions),
    ]
    if overflow_on:
        capabilities.append(cast("AbstractCapability[BTierDeps]", build_overflow_capability()))
    if extra:
        capabilities.extend(extra)
    if codemode_on:
        capabilities.append(
            build_codemode_capability(
                codemode_limits,
                max_retries=codemode_max_retries,
            )
        )
    return capabilities


async def run_b_turn(
    *,
    workspace: Workspace,
    session: SessionHandle,
    turn_id: str,
    triage: TriageResult,
    incoming_text: str,
    tool_set: ToolSet,
    body_cache: LoadedBodyCache,
    tool_executor: ToolExecutor,
    transport_bundle: ResolvedTierBModel,
    trace: TraceSink | None,
    steer_buffer: SteerInject | None,
    tool_context: ToolContext,
    extra_instructions: str | None = None,
    max_rounds: int | None = None,
    max_output_tokens: int | None = None,
    first_session_intro: bool = False,
    streaming_sink: StreamingSink | None = None,
    streaming_debounce_s: float = 1.0,
    full_index: bool = False,
    transcript_turns: list[str] | None = None,
    transcript_rows: Sequence[TranscriptRow] | None = None,
    turn_media: Sequence[TurnMediaItem] | None = None,
    return_partial_on_cancel: bool = False,
    operator_local_date: str = "",
) -> BTurnOutcome:
    """Execute one tier-B pydantic-ai agent loop (`specs/14-executor-tier-b.md` §2.1).

    Args:
        workspace (Workspace): Parsed workspace context for permission/policy decisions (§3.1).
        session (SessionHandle): Session identity for tracing + tool spill paths.
        turn_id (str): Turn identifier spanning Triager + executor spans.
        triage (TriageResult): Structured triage row (must be complexity **B** and not ``disregard``).
        incoming_text (str): User message text for this turn.
        tool_set (ToolSet): Narrowed immutable catalog snapshot backing lazy ``load_tool`` metadata.
        body_cache (LoadedBodyCache): Session-scoped lazy body cache (API surface; §3.2).
        tool_executor (ToolExecutor): Live registry sharing definitions with ``tool_set``.
        transport_bundle (ResolvedTierBModel): Resolved model id + ``Transport`` + ``ModelBudget``.
        trace (TraceSink | None): Optional structured trace sink (§7).
        steer_buffer (SteerInject | None): Optional gateway-owned steer queue (§4.5).
        tool_context (ToolContext): Template context cloned per dispatch (trace, permissions, ...).
        extra_instructions (str | None): Optional appended static instructions (e.g. BOOTSTRAP intro).
        max_rounds (int | None): Per-turn outer cap. Defaults to ``gateway.budget.tier_b_rounds``;
            the gateway passes ``gateway.budget.tier_b_rounds_expanded`` when retrying after a
            tier-C escalation that could not be dispatched (`specs/17-gateway.md` §2.6 step 9).
        max_output_tokens (int | None): Provider ``max_tokens`` override; defaults to
            ``gateway.budget.tier_b_max_output_tokens``. Gateway passes
            ``first_session_intro_max_output_tokens`` on BOOTSTRAP intro turns.
        first_session_intro (bool): When ``True``, tags structured logs for the
            first-session intro turn (gateway-scoped egress profile).
        streaming_sink (StreamingSink | None): Optional callback receiving the
            accumulated answer text after each pydantic-ai
            ``ModelRequestNode.stream(...).stream_text(...)`` chunk (`PROBLEMS.md`
            Priority 2 Mode 1 / Step 6). ``None`` disables streaming and the node
            loop iterates without tapping per-node text.
        streaming_debounce_s (float): Seconds passed to ``stream_text(debounce_by=...)``
            for the in-flight edit cadence; defaults to ``1.0`` which matches Telegram's
            ``editMessageText`` rate ceiling.
        full_index (bool): When ``True``, the harness ``model_copy``'s ``triage``
            to ``tools=<all registered names>`` while preserving ``triage.skills``
            so the executor sees the entire registry + full ``read_skills_index(names=None)``
            output (Step 7c — "Widening toolkit and retrying…" path). Triager-bound
            tool names are still pre-seeded for eager hydration (D1).
        transcript_turns (list[str] | None): Legacy ``role: text`` lines (text-only
            replay fallback when ``transcript_rows`` is absent).
        transcript_rows (Sequence[TranscriptRow] | None): Structured prior rows
            including optional ``provider_turn_messages`` for faithful replay (D8).
        turn_media (Sequence[TurnMediaItem] | None): Optional pre-hydrated inbound
            attachments; when omitted and triage flags vision/document, resolved via
            ``channel_router.load_turn_media`` or gateway DB summaries (W10).
        return_partial_on_cancel (bool): When ``True`` (gateway path), a
            ``asyncio.CancelledError`` from ``asyncio.wait_for`` returns a failed
            ``BTurnOutcome`` with ``successful_tools_called`` preserved instead of
            re-raising (``specs/17-gateway.md`` §10.25).
        operator_local_date (str): Operator-local calendar date ``YYYY-MM-DD`` for
            live-factual prompts (scores, news, schedules).

    Returns:
        BTurnOutcome: Terminal disposition plus outbound payloads for the gateway to deliver.

    Raises:
        ValueError: When triage routing inputs disagree with tier-B execution.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_b_turn)
        True
    """

    _ = workspace
    _ = body_cache
    if triage.complexity != ComplexityTier.B:
        msg = "run_b_turn requires triage.complexity == B"
        raise ValueError(msg)
    if triage.disregard:
        msg = "run_b_turn requires triage.disregard == False"
        raise ValueError(msg)

    # Capture triager bindings before any full-index widening (D1 / D5).
    triager_bound_tool_picks = tuple(triage.tools)
    triager_bound_skill_picks = tuple(triage.skills)

    # Step 7c (`PROBLEMS.md` Priority 1(e)): on a retry-with-full-index pass, widen
    # the tool catalog so the executor sees the entire registry and the full
    # ``read_skills_index(names=None)`` output while preserving triager-bound skills.
    full_index_tool_cap: int | None = None
    if full_index:
        all_tool_names = [d.name for d in tool_executor.definitions()]
        triage = triage.model_copy(
            update={"tools": all_tool_names},
        )
        # The widened retry must expose the ENTIRE registry; bypass the Triager tool
        # cap so the whole tool list (not just the first cap-many extras) is bound.
        full_index_tool_cap = len(all_tool_names)

    registry_tool_names_list = [d.name for d in tool_executor.definitions()]
    if not full_index and (
        set(triage.tools) & _EXECUTION_INTENT_TOOLS
        or set(triage.skills) & {"pdf"}
        or "pdf" in incoming_text.lower()
    ):
        recovery_ids = [
            name
            for name in (*DIAGNOSTIC_RECOVERY_TOOLS, *FILE_PIPELINE_TOOL_IDS)
            if name in registry_tool_names_list
        ]
        merged_tools = list(dict.fromkeys([*triage.tools, *recovery_ids]))
        if merged_tools != list(triage.tools):
            triage = triage.model_copy(update={"tools": merged_tools})

    registration = register_pydantic_tools(tool_set, triage, tier_b_tool_cap=full_index_tool_cap)
    instructions = _description_only_instructions(
        registration,
        catalog_lines=_full_tool_catalog_lines(tool_executor.definitions()),
    )
    if extra_instructions and extra_instructions.strip():
        instructions = f"{instructions}\n\n{extra_instructions.strip()}"
    triager_first_reply = (triage.first_message or "").strip()
    if triager_first_reply:
        instructions = (
            f"{instructions}\n\n"
            "Triager opener already delivered to the user:\n"
            f"  >>> {triager_first_reply}\n"
            "Continue from there. Do not repeat or contradict the opener; "
            "build on it with the substantive answer or action."
        )
    steer = steer_buffer or SteerInject()
    provider_rounds: list[int] = [0]
    content_root = Path(tool_context.workspace_path)
    effective_max_rounds = int(max_rounds) if max_rounds is not None else tier_b_rounds(workspace)
    effective_max_output_tokens = (
        int(max_output_tokens)
        if max_output_tokens is not None
        else resolve_effective_max_output_tokens(
            "tier_b",
            transport_bundle.model_id,
            workspace,
            content_root=content_root,
        )
    )
    count_planning = tier_b_count_planning(workspace)
    gateway_stream_debug = bool(
        workspace.logging is not None and workspace.logging.gateway_stream_debug
    )

    from sevn.logging.structured import debug_event, preview

    # When planning rounds are NOT counted toward the budget, pydantic-ai still tracks every
    # LLM call; give it generous headroom so a model that does a lot of planning before each
    # tool call does not trip on the safety net. The "real" budget is enforced by
    # ``provider_rounds`` which only increments on tool-call rounds when ``count_planning`` is
    # ``False`` (`specs/14-executor-tier-b.md` §5).
    pydantic_request_limit = effective_max_rounds if count_planning else effective_max_rounds * 3

    narrowed_permissions = apply_permission_scope_narrowing(
        tool_context.permissions,
        triage.permission_scope_narrowing,
    )
    tool_base = replace(
        tool_context,
        registry_version=tool_set.registry_version,
        permissions=narrowed_permissions,
        outbound_metadata=dict(tool_context.outbound_metadata),
        turn_id=turn_id,
        executor_tier="B",
    )
    from sevn.agent.adapters.tool_approval_bridge import get_tool_approval_bridge

    approval_bridge = get_tool_approval_bridge()
    if approval_bridge is not None:
        preapproved = approval_bridge.preapproved_tools(
            session.session_id,
            workspace_tools=dict(workspace.tools or {}),
        )
        if preapproved:
            tool_base = replace(tool_base, human_acknowledged_tools=preapproved)
    # Pre-seed triager-bound non-core tools so the model can call them directly
    # without a ``load_tool`` round. On full_index the catalog widens to ~40 tools;
    # seed only the triager's original picks (D1), not the entire registry.
    if full_index:
        seeded_tools: set[str] = set(triager_bound_tool_picks) - _NEVER_LAZY_NAMES
    else:
        seeded_tools = set(registration.tool_names) - _NEVER_LAZY_NAMES
    codemode_on = codemode_enabled(workspace, model_id=transport_bundle.model_id)
    if codemode_on:
        seeded_tools.add("run_code")
    registry_tool_names = frozenset(d.name for d in tool_executor.definitions())
    bound_tool_names = frozenset(registration.tool_names) | frozenset({"request_escalation"})
    if codemode_on:
        bound_tool_names = bound_tool_names | frozenset({"run_code"})
    triager_tools = frozenset(triage.tools)
    triager_skills = frozenset(triage.skills)
    # Names callable only inside ``run_code`` this turn. Used by the FunctionModel to
    # rewrite a contract-violating bare native call back into ``run_code`` (Layer 1,
    # `specs/14-executor-tier-b.md` §5.1). Empty when CodeMode is off → rewrite is a no-op.
    codemode_sandboxed_tool_names = (
        compute_codemode_eligible_names(
            triager_tools=triager_tools,
            triager_skills=triager_skills,
        )
        if codemode_on
        else frozenset()
    )
    web_thinking_extra, thinking_via_capability = build_web_thinking_extra_capabilities(
        workspace=workspace,
        model_id=transport_bundle.model_id,
        tool_executor=tool_executor,
        triage_tools=triage.tools,
        content_root=content_root,
        codemode_enabled=codemode_on,
    )
    capability_owned_tools = registry_tool_names_owned_by_web_capabilities(web_thinking_extra)
    codemode_web_policy = resolve_web_egress_domain_policy(workspace) if codemode_on else None
    registry_toolset = SevnRegistryToolset.from_registry(
        tool_executor,
        registration,
        extra_tools=[request_escalation_pydantic_tool()],
        codemode_enabled=codemode_on,
        triager_tools=triager_tools,
        triager_skills=triager_skills,
        exclude_tool_names=capability_owned_tools,
        codemode_web_policy=codemode_web_policy,
    )
    hook_config = TierBHookConfig(
        provider_round_counter=provider_rounds,
        max_rounds=effective_max_rounds,
        count_planning=count_planning,
        bound_tool_names=bound_tool_names,
        triager_first_reply=triager_first_reply,
    )
    tier_b_hooks = build_tier_b_hooks(hook_config)
    skill_caps = build_tier_b_skill_capabilities(
        triage_skills=triage.skills,
        skill_descriptions=tool_set.skill_descriptions,
        skills_manager=SkillsManager.shared(
            Path(tool_context.workspace_path),
            config=workspace,
            trace_sink=trace,
        ),
    )
    tool_allowlist = MutableToolAllowlist(
        base=bound_tool_names,
        registry_names=registry_tool_names,
        codemode_blocks_web_autogrants=codemode_on,
    )
    deps = BTierDeps(
        tool_executor=tool_executor,
        tool_context_template=tool_base,
        workspace_path=Path(tool_context.workspace_path),
        registry_version=tool_set.registry_version,
        meta_tool_names=meta_tool_name_frozenset(registration),
        loaded_tools=seeded_tools,
        steer_buffer=steer,
        tool_allowlist=tool_allowlist,
        triager_bound_tools=frozenset(triager_bound_tool_picks),
        triager_bound_skills=frozenset(triager_bound_skill_picks),
    )
    log_provenance_audit = is_log_provenance_intent_message(incoming_text)
    # Identity / capability questions ("who are you?", "which LLM model are you using?") are
    # answerable from the system prompt / persona, so a zero-tool answer is legitimate — the
    # triager-bound-tools mandate (G0) must not discard it into a canned "something went wrong"
    # (transcript-review-2026-06-22). Intent-gated, not content-gated: live-data fabrications
    # (prices, scores), audit narratives, and shell-bypass turns are NOT identity and still fail.
    self_knowledge_intent = is_identity_or_capability_message(incoming_text)
    bound_registry_tools = _triager_bound_registry_tools(triager_bound_tool_picks)
    if log_provenance_audit:
        must_satisfy_tools = frozenset({"log_query"})
    elif bound_registry_tools:
        must_satisfy_tools = bound_registry_tools
    else:
        must_satisfy_tools = frozenset()
    triager_bound_tool_choice: TriagerBoundToolChoiceContext | None = None
    if triager_bound_tool_picks or triager_bound_skill_picks:
        triager_bound_tool_choice = TriagerBoundToolChoiceContext(
            bound_tools=frozenset(triager_bound_tool_picks),
            bound_skills=frozenset(triager_bound_skill_picks),
            must_satisfy_tools=must_satisfy_tools,
            successful_tools_called=deps.successful_tools_called,
            successful_skills_called=deps.successful_skills_called,
            codemode_bound_tools_called=deps.codemode_bound_tools_called,
        )
    debug_event(
        "tier_b.input",
        session_id=session.session_id,
        turn_id=turn_id,
        model_id=transport_bundle.model_id,
        max_rounds=effective_max_rounds,
        max_output_tokens=effective_max_output_tokens,
        first_session_intro=first_session_intro,
        full_index=full_index,
        codemode_on=codemode_on,
        registry_version=tool_set.registry_version,
        tools=sorted(triage.tools),
        skills=sorted(triage.skills),
        seeded_tools=sorted(seeded_tools),
        triager_first_reply=preview(triager_first_reply),
    )

    # Replay prior turns as ``message_history`` (D8) before constructing the
    # FunctionModel so ``turn_message_start_index`` can classify replay stubs.
    message_history: list[ModelRequest | ModelResponse] = []
    if transcript_rows:
        replay_rows = list(transcript_rows)
        replay_provider_history = triage.replay_provider_history
        if log_provenance_audit:
            replay_rows = slim_transcript_for_log_provenance(replay_rows)
            replay_provider_history = False
        message_history = build_cross_turn_message_history(
            replay_rows,
            replay_provider_history=replay_provider_history,
        )
    else:
        for line in transcript_turns or ():
            if line.startswith("user: "):
                message_history.append(
                    ModelRequest(parts=[UserPromptPart(content=line[len("user: ") :])]),
                )
            elif line.startswith("assistant: "):
                message_history.append(
                    ModelResponse(parts=[TextPart(content=line[len("assistant: ") :])]),
                )
    turn_message_start_index = (
        len(pydantic_messages_to_anthropic_messages(message_history)) if message_history else 0
    )

    # Build the pydantic tool list first so we can derive ``allowed_tool_names``
    # before constructing the FunctionModel.  The allowlist is the exact set
    # pydantic-ai exposes this turn; using it in the model prevents XML-recovered
    # tool calls for unbound tools (e.g. ``find_file``) from reaching the Anthropic
    # wire as ``tool_use`` blocks the provider rejects with HTTP 400 (W3.2).
    def _on_auto_granted_tool(tool_name: str) -> None:
        deps.loaded_tools.add(tool_name)

    function_model = build_tier_b_function_model(
        bundle=transport_bundle,
        steer_buffer=steer,
        trace=trace,
        session_id=session.session_id,
        turn_id=turn_id,
        provider_round_counter=provider_rounds,
        parent_span_id=tool_base.turn_span_id,
        count_planning=count_planning,
        max_rounds=effective_max_rounds,
        max_output_tokens=effective_max_output_tokens,
        agent="tier_b",
        content_root=content_root,
        user_id=tool_context.outbound_user_id or None,
        channel=tool_context.delivery_channel or None,
        workspace_id=tool_context.workspace_id or None,
        executor_tier="B",
        allowed_tool_names=tool_allowlist,
        on_granted_tool=_on_auto_granted_tool,
        lifecycle_via_hooks=True,
        thinking_via_capability=thinking_via_capability,
        turn_message_start_index=turn_message_start_index,
        codemode_sandboxed_tool_names=codemode_sandboxed_tool_names,
        triager_bound_tool_choice=triager_bound_tool_choice,
    )
    transport_name = transport_bundle.transport.name
    native_model_active = native_model_enabled(workspace, ModelSlot.tier_b)
    if native_model_active:
        providers_obj = providers_section_dict(workspace.providers)
        proxy_base = ProcessSettings().proxy_url or "http://127.0.0.1:8787"
        native_ctx = default_native_model_context(
            slot=ModelSlot.tier_b,
            model_id=transport_bundle.model_id,
            proxy_base=proxy_base,
            session_id=session.session_id,
            turn_id=turn_id,
            agent="tier_b",
            trace=trace,
            tier="B",
            parent_span_id=tool_base.turn_span_id,
            content_root=content_root,
            max_output_tokens=effective_max_output_tokens,
            providers_obj=providers_obj,
            user_id=tool_context.outbound_user_id or None,
            channel=tool_context.delivery_channel or None,
            workspace_id=tool_context.workspace_id or None,
            executor_tier="B",
            triager_bound_tool_choice=triager_bound_tool_choice,
        )
        model = resolve_pydantic_model_for_slot(workspace=workspace, ctx=native_ctx)
    else:
        model = function_model

    modality_support = resolve_tier_b_modality_support(
        model_id=transport_bundle.model_id,
        transport_name=transport_name,
        native_model_active=native_model_active,
    )
    resolved_turn_media = resolve_turn_media_items(
        session_id=session.session_id,
        turn_id=turn_id,
        content_root=content_root,
        triage_requires_vision=triage.requires_vision,
        triage_requires_document=triage.requires_document,
        turn_media=turn_media,
        channel_router=tool_context.channel_router,
    )
    user_prompt: UserPromptContent = build_tier_b_user_prompt(
        incoming_text=incoming_text,
        triage_requires_vision=triage.requires_vision,
        triage_requires_document=triage.requires_document,
        turn_media=resolved_turn_media,
        session_id=session.session_id,
        support=modality_support,
    )
    skill_descriptions = _resolve_skill_descriptions(
        allowed=triage.skills,
        registry=tool_set.skill_descriptions,
    )
    if first_session_intro:
        prompt_parts = build_tier_b_intro_prompt_parts(content_root)
        non_empty_parts = [p for p in prompt_parts if p.strip()]
        persona_block = prompt_parts[-1]  # load_persona_block_intro is last
        static_parts = prompt_parts[:-1]
        debug_event(
            "tier_b.intro_prompt_slim",
            session_id=session.session_id,
            turn_id=turn_id,
            persona_chars=len(persona_block),
            static_chars=sum(len(p) for p in static_parts),
            part_count=len(non_empty_parts),
        )
    else:
        from sevn.agent.context_manifest import tier_b_system_prompt_builders

        prompt_parts = tier_b_system_prompt_builders(
            content_root,
            operator_local_date=operator_local_date,
            log_provenance_audit=log_provenance_audit,
            codemode_on=codemode_on,
            triager_bound_skill_picks=triager_bound_skill_picks,
            triager_bound_tool_picks=triager_bound_tool_picks,
            skill_descriptions=skill_descriptions,
            workspace=workspace,
        )
    system_prompt = "\n\n".join(p for p in prompt_parts if p.strip())
    capability_extra = list(skill_caps)
    if web_thinking_extra:
        capability_extra.extend(web_thinking_extra)
    # Enforce the triager-bound toolset on the FIRST tier-B round: when the triager
    # narrowed to specific registry tools, hide always-on meta tools (load_tool,
    # run_skill_script, list_registry, …) on round 1 so the model must use what it
    # was given instead of wandering into meta/skill calls and looping. Provider-
    # agnostic (toolset layer). Later rounds expose the full toolset. Skipped when
    # the triager bound no real tools (open-ended turns keep full discovery).
    triager_bound_registry_tools = frozenset(registration.tool_names) - _NEVER_LAZY_NAMES
    model_toolset: AbstractToolset[BTierDeps] = registry_toolset
    if triager_bound_registry_tools:
        model_toolset = registry_toolset.filtered(bound_tools_only_first_round(bound_tool_names))
    agent = Agent(
        model=model,
        toolsets=[model_toolset],
        deps_type=BTierDeps,
        capabilities=build_tier_b_capabilities(
            hooks=tier_b_hooks,
            extra=capability_extra or None,
            codemode_on=codemode_on,
            codemode_limits=codemode_resource_limits(workspace),
            codemode_max_retries=codemode_max_retries(workspace),
        ),
        system_prompt=system_prompt,
        instructions=instructions,
        retries=TIER_B_TOOL_MAX_RETRIES,
    )
    from sevn.agent.tracing.agent_context import build_tier_b_context_attrs, emit_context_span

    await emit_context_span(
        trace,
        kind="tier_b.context",
        session_id=session.session_id,
        turn_id=turn_id,
        parent_span_id=tool_base.turn_span_id,
        tier="B",
        attrs=build_tier_b_context_attrs(
            incoming_text=incoming_text,
            triager_first_reply=triager_first_reply,
            system_prompt=system_prompt,
            instructions=instructions,
            message_history=message_history,
            user_prompt=user_prompt,
            tools=triage.tools,
            skills=triage.skills,
        ),
    )
    span_parent = str(uuid.uuid4())
    turn_root = tool_base.turn_span_id
    stream_unavailable_logged = False
    stream_unavailable_suppressed = 0
    stream_skip_logged = False
    streaming_aborted_logged = False
    model_id = transport_bundle.model_id

    # Gate progressive streaming per transport capability. Batch-only wires (e.g.
    # the MiniMax Anthropic-compatible transport) resolve the full assistant
    # message in one ``complete`` round-trip and only *simulate* streaming, so a
    # ``node.stream`` tap yields no latency benefit and intermittently 400s on
    # the proxy. When the transport opts out, skip straight to the non-streaming
    # node loop and log a single ``streaming_disabled`` line rather than paying a
    # failed round-trip + per-round ``streaming_unavailable`` error every turn
    # (`specs/14-executor-tier-b.md` §2.3). Button attach is already decoupled
    # from streaming state (`turn_finalizer`), so disabling streaming is safe.
    transport_supports_streaming = getattr(transport_bundle.transport, "supports_streaming", True)
    streaming_disabled_by_transport = False
    streaming_disabled_by_bound_work = False
    if streaming_sink is not None and not transport_supports_streaming:
        streaming_disabled_by_transport = True
        logger.info(
            "b_harness.streaming_disabled reason=transport_unsupported session_id={} "
            "turn_id={} model_id={} transport={}",
            session.session_id,
            turn_id,
            model_id,
            transport_name,
        )
        streaming_sink = None
    # W6 / 7b8454 mitigation B: tool- or skill-bound turns disable progressive
    # streaming so pydantic-ai never interleaves an unconsumed ``node.stream()``
    # with the next ``run()`` round (``You must finish streaming before calling run()``).
    if streaming_sink is not None and (bound_registry_tools or triager_bound_skill_picks):
        streaming_disabled_by_bound_work = True
        logger.info(
            "b_harness.streaming_disabled reason=bound_tools_or_skills session_id={} "
            "turn_id={} model_id={} transport={} tools={} skills={}",
            session.session_id,
            turn_id,
            model_id,
            transport_name,
            sorted(bound_registry_tools),
            sorted(triager_bound_skill_picks),
        )
        streaming_sink = None
    now = time_ns()
    await _emit(
        trace,
        TraceEvent(
            kind="b_turn",
            span_id=span_parent,
            parent_span_id=turn_root,
            session_id=session.session_id,
            turn_id=turn_id,
            tier="B",
            ts_start_ns=now,
            ts_end_ns=None,
            status="started",
            attrs={"complexity": "B"},
        ),
    )

    try:
        with attach_turn_trace_context(turn_root):
            async with agent.iter(
                user_prompt,
                deps=deps,
                usage_limits=UsageLimits(request_limit=pydantic_request_limit),
                message_history=message_history or None,
            ) as agent_run:
                if streaming_sink is None:
                    if (
                        not stream_skip_logged
                        and not streaming_disabled_by_transport
                        and not streaming_disabled_by_bound_work
                    ):
                        stream_skip_logged = True
                        logger.info(
                            "b_harness.streaming_skipped reason=no_sink session_id={} turn_id={} "
                            "model_id={} transport={}",
                            session.session_id,
                            turn_id,
                            model_id,
                            transport_name,
                        )
                    async for _node in agent_run:
                        # W2.3: cooperative cancel checkpoint between rounds so a
                        # mid-turn cancel is honoured promptly even across a CPU-bound
                        # gap between provider rounds.
                        await asyncio.sleep(0)
                else:
                    # Priority 2 Mode 1 (`PROBLEMS.md`): when a streaming sink is
                    # wired, tap each ``ModelRequestNode``'s text stream so the
                    # placeholder message edits land progressively. Tool nodes are
                    # iterated normally — token streaming only matters on model
                    # request nodes (where the answer text is produced).
                    streaming_active = True
                    async for node in agent_run:
                        # W2.3: cooperative cancel checkpoint between rounds (see
                        # non-streaming branch above).
                        await asyncio.sleep(0)
                        if not isinstance(node, ModelRequestNode):
                            continue
                        if not streaming_active or streaming_sink is None:
                            continue
                        try:
                            await _consume_model_request_stream(
                                node,
                                agent_run.ctx,
                                sink=streaming_sink,
                                debounce_s=streaming_debounce_s,
                                session_id=session.session_id,
                                turn_id=turn_id,
                                gateway_stream_debug=gateway_stream_debug,
                            )
                        except Exception as exc:
                            exc_lower = str(exc).lower()
                            if "finish streaming" in exc_lower:
                                if not streaming_aborted_logged:
                                    streaming_aborted_logged = True
                                    logger.info(
                                        "b_harness.streaming_aborted reason=finish_streaming_contract "
                                        "session_id={} turn_id={} model_id={} transport={}",
                                        session.session_id,
                                        turn_id,
                                        model_id,
                                        transport_name,
                                    )
                                streaming_active = False
                                streaming_sink = None
                                continue
                            # Streaming is best-effort. If the node refuses to
                            # stream (e.g., tool-call-only response with no text),
                            # fall through — the node still executes during the
                            # outer ``async for`` advance.
                            if stream_unavailable_logged:
                                stream_unavailable_suppressed += 1
                            else:
                                stream_unavailable_logged = True
                                logger.info(
                                    "b_harness.streaming_unavailable reason={} session_id={} "
                                    "turn_id={} model_id={} transport={} suppressed_count={}",
                                    exc,
                                    session.session_id,
                                    turn_id,
                                    model_id,
                                    transport_name,
                                    stream_unavailable_suppressed,
                                )
    except asyncio.CancelledError:
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "error": "CancelledError",
                    "rounds_used": provider_rounds[0],
                    "reason": "timeout_cancel",
                },
            ),
        )
        if return_partial_on_cancel:
            return BTurnOutcome(
                status="failed",
                final_messages=(),
                escalation=None,
                rounds_used=provider_rounds[0],
                failure_detail=EXECUTOR_TIMEOUT_CANCEL_DETAIL,
                **cast("Any", _outcome_tool_fields(deps)),
            )
        raise
    except UsageLimitExceeded:
        if deps.escalation is not None:
            escalation = deps.escalation
            line = escalation.user_visible_message
        else:
            line = TIER_B_ROUND_BUDGET_TEMPLATE.format(tier="C")
            escalation = EscalationRequest(
                reason="round_budget_exhausted",
                target_tier="C",
                user_visible_message=line,
            )
        # Stamp the originally-requested tools so the C/D re-triage can union-merge
        # them back in, preventing the escalation note from dropping e.g. ``serp``.
        if not escalation.original_tools:
            escalation = replace(escalation, original_tools=tuple(triager_bound_tool_picks))
        msgs = (ChannelPayload(text=line),)
        end = time_ns()
        trace_attrs: dict[str, object] = {
            "rounds_used": provider_rounds[0],
            "registry_version": tool_set.registry_version,
        }
        if escalation.reason == "repeated_wrong_tool_call":
            trace_attrs["repeated_wrong_tool_call"] = True
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="escalated",
                attrs=trace_attrs,
            ),
        )
        return BTurnOutcome(
            status="escalated",
            final_messages=msgs,
            escalation=escalation,
            rounds_used=provider_rounds[0],
            **cast("Any", _outcome_tool_fields(deps)),
        )
    except BaseException as exc:
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={"error": type(exc).__name__},
            ),
        )
        if isinstance(exc, Exception):
            return BTurnOutcome(
                status="failed",
                final_messages=(),
                escalation=None,
                rounds_used=provider_rounds[0],
                failure_detail=str(exc),
                **cast("Any", _outcome_tool_fields(deps)),
            )
        raise

    if deps.escalation is not None:
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="escalated",
                attrs={"rounds_used": provider_rounds[0]},
            ),
        )
        if deps.channel_payloads:
            msgs_escalation: tuple[ChannelPayload, ...] = tuple(deps.channel_payloads)
        else:
            msgs_escalation = (ChannelPayload(text=deps.escalation.user_visible_message),)
        # Stamp the originally-requested tools (same union-merge contract as the
        # UsageLimitExceeded path above) so C/D re-triage never silently drops them.
        final_escalation = deps.escalation
        if not final_escalation.original_tools:
            final_escalation = replace(
                final_escalation,
                original_tools=tuple(triager_bound_tool_picks),
            )
        return BTurnOutcome(
            status="escalated",
            final_messages=msgs_escalation,
            escalation=final_escalation,
            rounds_used=provider_rounds[0],
            **cast("Any", _outcome_tool_fields(deps)),
        )

    result = agent_run.result
    provider_turn_messages: tuple[dict[str, object], ...] = ()
    turn_messages: list[ModelRequest | ModelResponse] = []
    if result is not None:
        turn_messages = list(result.new_messages())
        raw_rows = serialize_provider_turn_messages(turn_messages)
        sanitized_rows, _ = sanitize_provider_turn_messages_for_storage(raw_rows)
        provider_turn_messages = tuple(sanitized_rows)
    output_text = ""
    if result is not None:
        for turn_msg in reversed(turn_messages):
            if isinstance(turn_msg, ModelResponse):
                output_text = _display_text_from_model_response(turn_msg)
                if output_text.strip():
                    break
        if not output_text.strip():
            output_text = str(result.output)
    stop_reason = last_model_stop_reason(turn_messages)
    final_list = [*deps.channel_payloads]
    if output_text.strip():
        stripped_output = _strip_opener_echo(output_text, triager_first_reply)
        if stripped_output.strip():
            final_list.append(
                ChannelPayload(
                    text=append_output_truncation_notice(stripped_output, stop_reason),
                ),
            )
    msgs_tuple = tuple(final_list)
    # Opener-only / echo-only final (`PROBLEMS.md` P2; spec §2.7): the model shipped
    # just a restated opener ("On it…", "Here you go:") or echoed the user's words and
    # dropped the substantive answer — including a successful `list_registry` result.
    # When the *only* candidate text is the model's own output and it carries no body
    # beyond the opener, reclassify as a failed/empty outcome so the gateway runs its
    # widened-retry / typed no-answer path instead of shipping the bare ack. Guarded so
    # tool-emitted ``channel_payloads`` (e.g. send_file confirmations) are never voided.
    execution_filler = _is_execution_filler_completion(
        rounds_used=provider_rounds[0],
        text=output_text,
        opener=triager_first_reply,
        triage_tools=triager_bound_tool_picks,
    )
    if (
        not deps.channel_payloads
        and msgs_tuple
        and (_is_opener_only_output(output_text, triager_first_reply) or execution_filler)
    ):
        # Inject a corrective steer so the widened retry has explicit guidance to call
        # the bound tool(s) or give the answer — the opener-only reclassify previously
        # steered nothing, so the model repeated the opener (Mode A; PROBLEMS.md P2).
        steer.inject_pending(
            steer_for_opener_only(
                triager_bound_tool_picks,
                triager_bound_skill_picks,
            ),
        )
        debug_event(
            "tier_b.opener_only",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            first_text=preview(output_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "execution_filler" if execution_filler else "opener_only_output",
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail=(
                "execution-filler output (no tool calls)"
                if execution_filler
                else "opener-only output (no substantive answer)"
            ),
            **cast("Any", _outcome_tool_fields(deps)),
        )
    # P4 ("all talk, no walk"): a zero-tool finalize whose only body is a fresh
    # motion-promise ("On it — rendering the PDF now.", "Right. Talking is done.
    # Doing.", "Fair. Executing now.") promised action but ran nothing. The opener-only
    # guard above already owns bare opener echoes ("On it — let me pull that now."); this
    # guard catches the residual motion-promise family it misses. Mirrors the
    # ``tool_unavailable_claim`` guard: inject a steer that forces the next attempt to
    # actually act (or state what blocks it), then reclassify as failed so the gateway
    # runs its widened-retry path with the steer pending — and, if that also produces
    # nothing, ships an honest typed no-answer instead of the empty promise. This closes
    # the double-ack: the triager already sent an opener, so tier-B must not finalize with
    # a second contentless ack. Guarded so tool-emitted ``channel_payloads`` are never
    # voided and a turn that legitimately ran tools is never flagged.
    if (
        not deps.channel_payloads
        and msgs_tuple
        and _is_promised_but_idle(
            rounds_used=provider_rounds[0],
            text=output_text,
            opener=triager_first_reply,
        )
    ):
        steer.inject_pending(steer_for_promised_action())
        debug_event(
            "tier_b.promised_but_idle",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            first_text=preview(output_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "promised_but_idle",
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="promised_but_idle (motion-promise, no tool calls)",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    # W5.3 / F4: zero-tool rounds whose output is a near-verbatim copy of a registered
    # tool description are a "leaked schema" failure — the model read out its own tool
    # description instead of calling the tool.  Reclassify as failed so the gateway can
    # run its widened-retry / no-answer path.  Guard: only fires when no tool calls
    # occurred (``rounds_used == 0``) and no channel_payloads were produced by tools.
    if (
        not deps.channel_payloads
        and msgs_tuple
        and provider_rounds[0] == 0
        and _is_tool_description_leak(output_text, registration.tool_descriptions)
    ):
        debug_event(
            "tier_b.tool_description_leak",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            first_text=preview(output_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "tool_description_leak",
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="zero-tool output matched a tool description (F4 leak)",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    # W2 / F2: block confabulated "I can't call `<tool>`" answers when the tool is bound.
    candidate_text = output_text.strip() or (msgs_tuple[-1].text.strip() if msgs_tuple else "")
    unavailable_tool = claims_bound_tool_unavailable(
        candidate_text,
        frozenset(triager_bound_tool_picks),
    )
    if unavailable_tool and unavailable_tool not in deps.grounding_tools_called and msgs_tuple:
        steer.inject_pending(steer_for_direct_tool_call(unavailable_tool))
        debug_event(
            "tier_b.tool_unavailable_claim",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            tool=unavailable_tool,
            first_text=preview(candidate_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "tool_unavailable_claim",
                    "tool": unavailable_tool,
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail=f"tool_unavailable_claim:{unavailable_tool}",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    # G0 (triager-bound tool mandate): runs after opener-only, promised-but-idle,
    # tool-description-leak, and tool-unavailable-claim guards so those narrower
    # failure_detail values win when they apply. Catches long fabricated answers
    # when the triager bound tools/skills but tier-B finalized with zero tool rounds
    # and none of the bound names succeeded.
    if (
        not deps.channel_payloads
        and not self_knowledge_intent
        and (triager_bound_tool_picks or triager_bound_skill_picks)
        and provider_rounds[0] == 0
        and not triager_bound_tools_satisfied(
            bound_tools=triager_bound_tool_picks,
            bound_skills=triager_bound_skill_picks,
            successful_tools_called=frozenset(deps.successful_tools_called),
            successful_skills_called=frozenset(deps.successful_skills_called),
            codemode_bound_tools_called=frozenset(deps.codemode_bound_tools_called),
        )
    ):
        steer.inject_pending(
            steer_for_triager_bound_tools_unused(
                triager_bound_tool_picks,
                triager_bound_skill_picks,
            ),
        )
        debug_event(
            "tier_b.triager_bound_tools_unused",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            tools=sorted(triager_bound_tool_picks),
            skills=sorted(triager_bound_skill_picks),
            first_text=preview(output_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "triager_bound_tools_unused",
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="triager_bound_tools_unused",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    _, file_blocked = apply_file_delivery_grounding_guard(
        candidate_text,
        successful_tools_called=frozenset(deps.successful_tools_called),
        had_tool_failures=deps.tool_failure_count > 0,
    )
    if file_blocked:
        debug_event(
            "tier_b.fabricated_file_delivery",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            first_text=preview(candidate_text, limit=400),
            last_tool_failure=deps.last_tool_failure_name,
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "fabricated_file_delivery",
                    "last_tool_failure": deps.last_tool_failure_name,
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="fabricated_file_delivery",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    _, live_factual_blocked = apply_live_factual_grounding_guard(
        candidate_text,
        successful_tools_called=frozenset(deps.successful_tools_called),
    )
    if live_factual_blocked and provider_rounds[0] > 0:
        debug_event(
            "tier_b.fabricated_live_factual",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            first_text=preview(candidate_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "fabricated_live_factual",
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="fabricated_live_factual",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    if not msgs_tuple:
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={"rounds_used": provider_rounds[0]},
            ),
        )
        report = format_tier_b_operator_failure_report(
            failure_detail="no assistant output produced",
            tool_name=deps.last_tool_failure_name,
            tool_error=deps.last_tool_failure_detail,
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(ChannelPayload(text=report),),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="no assistant output produced",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    # W3 / D3: shell bypass safety net — blocks 816cba when terminal_run succeeded but bound
    # file/search tools did not (dispatch block in tier_b_tools is the primary guard).
    if not deps.channel_payloads and _bound_tools_bypassed_via_shell(
        triager_bound_tool_picks=triager_bound_tool_picks,
        successful_tools_called=frozenset(deps.successful_tools_called),
        incoming_text=incoming_text,
    ):
        steer.inject_pending(
            "Triager bound file/search tools — use `search_in_file` / `read`, not shell grep.",
        )
        debug_event(
            "tier_b.bound_tools_bypassed_via_shell",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            tools=sorted(triager_bound_tool_picks),
            successful_tools=sorted(deps.successful_tools_called),
            first_text=preview(output_text, limit=400),
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "bound_tools_bypassed_via_shell",
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="bound_tools_bypassed_via_shell",
            **cast("Any", _outcome_tool_fields(deps)),
        )
    # W2 / D4: completed-with-zero-bound-tools safety net — blocks bc75f9-style narrative
    # audits when no bound registry tool succeeded (even if rounds_used > 0 slipped through).
    # Identity/capability questions are exempt (answerable from context) — same intent gate as G0.
    if (
        not deps.channel_payloads
        and not self_knowledge_intent
        and (bound_registry_tools or triager_bound_skill_picks)
        and triager_bound_tool_choice is not None
        and not triager_bound_tool_choice.satisfied()
    ):
        steer.inject_pending(
            steer_for_triager_bound_tools_unused(
                triager_bound_tool_picks,
                triager_bound_skill_picks,
            ),
        )
        debug_event(
            "tier_b.triager_bound_tools_unused",
            session_id=session.session_id,
            turn_id=turn_id,
            rounds_used=provider_rounds[0],
            tools=sorted(triager_bound_tool_picks),
            skills=sorted(triager_bound_skill_picks),
            first_text=preview(output_text, limit=400),
            completed_reclassify=True,
        )
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="b_turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=span_parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier="B",
                ts_start_ns=now,
                ts_end_ns=end,
                status="failed",
                attrs={
                    "rounds_used": provider_rounds[0],
                    "reason": "triager_bound_tools_unused",
                    "completed_reclassify": True,
                },
            ),
        )
        return BTurnOutcome(
            status="failed",
            final_messages=(),
            escalation=None,
            rounds_used=provider_rounds[0],
            failure_detail="triager_bound_tools_unused",
            **cast("Any", _outcome_tool_fields(deps)),
        )

    end = time_ns()
    await _emit(
        trace,
        TraceEvent(
            kind="b_turn",
            span_id=str(uuid.uuid4()),
            parent_span_id=span_parent,
            session_id=session.session_id,
            turn_id=turn_id,
            tier="B",
            ts_start_ns=now,
            ts_end_ns=end,
            status="completed",
            attrs={
                "rounds_used": provider_rounds[0],
                "registry_version": tool_set.registry_version,
            },
        ),
    )
    debug_event(
        "tier_b.output",
        session_id=session.session_id,
        turn_id=turn_id,
        status="completed",
        rounds_used=provider_rounds[0],
        messages=len(msgs_tuple),
        first_text=preview(msgs_tuple[0].text if msgs_tuple else "", limit=400),
    )
    return BTurnOutcome(
        status="completed",
        final_messages=msgs_tuple,
        escalation=None,
        rounds_used=provider_rounds[0],
        provider_turn_messages=provider_turn_messages,
        **cast("Any", _outcome_tool_fields(deps)),
    )


__all__ = ["run_b_turn"]
