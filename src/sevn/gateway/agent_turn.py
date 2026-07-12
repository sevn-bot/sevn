"""Production agent dispatch glue (`specs/17-gateway.md` §2.6).

Module: sevn.gateway.agent_turn
Depends: sevn.agent.triager, sevn.agent.executors.b_harness, sevn.gateway.channel_router,
    sevn.gateway.triage_context

Exports:
    build_agent_run_turn — factory returning ``RunTurnFn`` for Triager + tier A/B/C/D.
    build_intro_extra_instructions — pure helper: ``extra_parts`` for first-session intro turns (D5).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import time_ns
from typing import Any, cast

from loguru import logger

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import (
    EXECUTOR_TIMEOUT_CANCEL_DETAIL,
    BTurnOutcome,
    EscalationRequest,
    ResolvedTierBModel,
    SessionHandle,
    SteerInject,
)
from sevn.agent.executors.cd_harness import ImmediateApprovedPlanGate, NoOpPlanGate, run_cd_turn
from sevn.agent.executors.cd_types import ResolvedCdOuterModels
from sevn.agent.executors.plan_gate_store import supersede_awaiting_for_session
from sevn.agent.grounding import (
    EVIDENCE_TOOLS,
    apply_audit_evidence_guard,
    apply_file_delivery_grounding_guard,
    apply_zero_tool_grounding_guard,
    claims_bound_tool_unavailable,
    is_routing_footer_query,
    steer_for_direct_tool_call,
    steer_for_summarize_after_fetch,
    tier_b_routing_footer_inject,
    tier_b_self_architecture_inject,
)
from sevn.agent.openers import is_bare_opener, strip_opener_echo
from sevn.agent.persona import tier_b_repo_access_prompt
from sevn.agent.provider_history_keys import (
    PROVIDER_TURN_MESSAGES_KEY,
    SUCCESSFUL_TOOLS_KEY,
)
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.resolve import resolve_model
from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceSink
from sevn.agent.triager.context import ApprovedUserTurn
from sevn.agent.triager.errors import TriagerUnavailable
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.routing_policy import is_repo_code_intent_message
from sevn.agent.triager.run import triage_turn
from sevn.code_understanding.effective_settings import effective_graphify_settings
from sevn.code_understanding.graphify import resolve_active_profiles_cached
from sevn.code_understanding.triager_orientation import (
    infer_orientation_intent,
    orientation_block_for_workspace,
)
from sevn.config.defaults import (
    DEFAULT_CASCADE_BUDGET_S,
    DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S,
    DEFAULT_TIER_B_RETRY_HISTORY_TURNS,
    DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S,
)
from sevn.config.model_resolution import (
    ModelSlot,
    resolve_model_slot,
    resolve_transport_for_model_id,
)
from sevn.config.settings import ProcessSettings
from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace
from sevn.config.workspace_config import (
    WorkspaceConfig,
    cascade_budget_s,
    tier_b_answer_mode,
    tier_b_executor_timeout_s,
    tier_b_rounds_expanded,
    tier_cd_executor_timeout_s,
    tool_debug_result_max_chars,
)
from sevn.gateway.cascade_budget import CascadeBudget
from sevn.gateway.channel_router import (
    ChannelRouter,
    IncomingMessage,
    OutgoingMessage,
    RunTurnFn,
    outbound_routing_metadata,
)
from sevn.gateway.commands.core_commands import CoreCommandHandler
from sevn.gateway.commands.diagnostic_commands import DiagnosticCommandHandler
from sevn.gateway.commands.evolution_chat_bridge import EvolutionChatBridge
from sevn.gateway.commands.evolution_commands import EvolutionCommandHandler
from sevn.gateway.commands.evolution_issue_commands import FileIssueCommandHandler
from sevn.gateway.commands.menu_action_router import MenuActionRouter
from sevn.gateway.commands.menu_command_invoke import MenuCommandInvoker
from sevn.gateway.commands.menu_form_handler import MenuFormHandler
from sevn.gateway.commands.platform_commands import PlatformCommandHandler
from sevn.gateway.commands.self_improve_commands import SelfImproveCommandHandler
from sevn.gateway.dashboard_pin import DashboardPinPublisher
from sevn.gateway.evolution_approval_gate import (
    EvolutionApprovalCallbackHandler,
    EvolutionApprovalWaitRegistry,
)
from sevn.gateway.first_session import (
    bootstrap_capture_active,
    bootstrap_capture_instructions,
    first_session_intro_max_output_tokens,
    load_bootstrap_markdown_cached,
    mark_intro_state,
    maybe_mark_intro_done_if_bootstrap_complete,
    tier_b_intro_instructions,
)
from sevn.gateway.menu import ConfigMenuHandler, MenuCallbackHandler
from sevn.gateway.plan_gate import PlanGateCallbackHandler, PlanGateWaitRegistry, SqlitePlanGate
from sevn.gateway.post_turn_hooks import PostTurnContext, run_post_turn_hooks
from sevn.gateway.session_manager import latest_messages, load_session_row
from sevn.gateway.telegram_quick_actions import (
    GATEWAY_OUTBOUND_PHASE_KEY,
    QuickActionCallbackHandler,
)
from sevn.gateway.triage_audit import persist_triage_decision
from sevn.gateway.triage_context import (
    is_triager_enabled,
    passthrough_triage_result,
    registry_snapshot_from_tool_set,
    session_view_from_session,
    triage_context_from_session,
    window_transcript,
)
from sevn.gateway.turn_finalizer import TierBAnswerFinalizer
from sevn.gateway.turn_media import attachment_hints_for_triager, load_turn_media_summaries
from sevn.gateway.turn_metadata import record_turn_finished, record_turn_start
from sevn.prompts.fallbacks import (  # re-exported for backward compatibility
    ASSISTANT_NO_OUTPUT_PLACEHOLDER,
    ESCALATION_UNAVAILABLE_USER_MESSAGE,
    EXECUTOR_NO_ANSWER_FALLBACK,  # noqa: F401 — re-export + doctest
    NO_ANSWER_MESSAGES,
    TIER_UNSUPPORTED_USER_MESSAGE,
    format_cascade_budget_exhausted_message,
    is_retry_back_reference_phrase,
    looks_like_unfinished_assistant_reply,
    render_no_answer_message,
)
from sevn.tools.base import ToolDefinition
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import (
    AllowAllPermissionPolicy,
    AttributeBasedPermissionPolicy,
    DenyingPermissionPolicy,
    PermissionPolicy,
    resolve_principal,
)
from sevn.tools.registry import build_session_registry
from sevn.tools.runtime_dispatch import RuntimeToolBindings
from sevn.workspace.layout import WorkspaceLayout

# Typed reason → user-facing line lives in ``sevn.prompts.fallbacks.NO_ANSWER_MESSAGES``.
# Re-exported here for tests that import ``_NO_ANSWER_MESSAGES`` from this module.
_NO_ANSWER_MESSAGES = NO_ANSWER_MESSAGES


def _collect_partial_progress(
    *,
    finalizer: TierBAnswerFinalizer | None,
    outcome: Any | None,
) -> str | None:
    """Gather best-effort partial answer text before a cascade cap fires (D7).

    Args:
        finalizer (TierBAnswerFinalizer | None): Placeholder finalizer for this turn.
        outcome (Any | None): Tier-B ``BTurnOutcome`` when the executor returned one.

    Returns:
        str | None: Concatenated partial text, or ``None`` when nothing was captured.

    Examples:
        >>> _collect_partial_progress(finalizer=None, outcome=None) is None
        True
    """
    if finalizer is not None:
        streamed = finalizer.partial_progress_text
        if streamed:
            return streamed
    if outcome is not None:
        parts = [
            (payload.text or "").strip()
            for payload in getattr(outcome, "final_messages", ())
            if (payload.text or "").strip()
        ]
        if parts:
            return "\n\n".join(parts)
    return None


# Failure signatures that re-running tier-B with the full toolkit and an expanded
# round budget cannot change. Widening only helps tool/scope gaps; a parse/schema
# fault in the model's structured-output contract reproduces identically, so the
# widened retry (and the C/D escalation behind it) is pure latency + budget cost.
_DETERMINISTIC_HARNESS_FAILURE_MARKERS: tuple[str, ...] = (
    "schema/parse failed",
    "could not parse the execution plan",
    "decompose schema",
    # P7: transport/shape faults — scoped non-stream fallback already ran; widening
    # to the full toolkit cannot fix invalid-params or empty-stream failures.
    "transportbadrequest",
    "llm_transport_bad_request",
    "invalid params",
    "returned 400",
    "complete_stream produced no final",
    "upstream sse",
)
# P9: suppress the "interrupted" terminal when cancel-mode supersession is imminent.
_CANCEL_INTERRUPT_SUPPRESS_S = 5.0


def _is_deterministic_harness_failure(
    *,
    no_answer_reason: str | None,
    outcome: Any | None,
) -> bool:
    """Whether the tier-B failure is a non-recoverable harness/parse fault.

    Distinguishes deterministic contract failures (a parse/schema fault the
    model will reproduce on every call) from transient tool/scope gaps that the
    widened retry exists to rescue. Only the latter benefit from re-running.

    Args:
        no_answer_reason (str | None): Machine label when the executor raised or timed out.
        outcome (Any | None): Tier-B outcome when the harness returned normally.

    Returns:
        bool: ``True`` when a deterministic failure signature is present.

    Examples:
        >>> from types import SimpleNamespace
        >>> o = SimpleNamespace(failure_detail="cd.decompose schema/parse failed")
        >>> _is_deterministic_harness_failure(no_answer_reason=None, outcome=o)
        True
        >>> _is_deterministic_harness_failure(no_answer_reason="timeout", outcome=None)
        False
    """
    detail = str(getattr(outcome, "failure_detail", "") or "")
    blob = f"{detail} {no_answer_reason or ''}".lower()
    return any(marker in blob for marker in _DETERMINISTIC_HARNESS_FAILURE_MARKERS)


def _tier_b_tools_succeeded_without_answer(outcome: Any | None) -> bool:
    """Whether tier-B fetched data but produced no deliverable user text.

    Args:
        outcome (Any | None): Tier-B outcome when the harness returned normally.

    Returns:
        bool: ``True`` when at least one tool returned ``ok=true`` but ``final_messages``
        are empty — a summarize/read pass should run instead of a full-index retry.

    Examples:
        >>> from types import SimpleNamespace
        >>> ok_fetch = SimpleNamespace(
        ...     status="failed",
        ...     final_messages=(),
        ...     successful_tools_called=frozenset({"get_page_content"}),
        ... )
        >>> _tier_b_tools_succeeded_without_answer(ok_fetch)
        True
        >>> empty = SimpleNamespace(
        ...     status="failed",
        ...     final_messages=(),
        ...     successful_tools_called=frozenset(),
        ... )
        >>> _tier_b_tools_succeeded_without_answer(empty)
        False
    """
    if outcome is None:
        return False
    successful: frozenset[str] = frozenset(
        getattr(outcome, "successful_tools_called", frozenset()) or frozenset(),
    )
    if not successful:
        return False
    finals = getattr(outcome, "final_messages", ()) or ()
    return not any((getattr(payload, "text", "") or "").strip() for payload in finals)


def _is_executor_timeout_cancel_outcome(outcome: Any | None) -> bool:
    """Whether tier-B returned partial tool state after ``wait_for`` cancellation.

    Args:
        outcome (Any | None): ``BTurnOutcome`` from ``run_b_turn``.

    Returns:
        bool: ``True`` when ``failure_detail`` marks a timeout cancel partial.

    Examples:
        >>> from types import SimpleNamespace
        >>> partial = SimpleNamespace(failure_detail=EXECUTOR_TIMEOUT_CANCEL_DETAIL)
        >>> _is_executor_timeout_cancel_outcome(partial)
        True
        >>> _is_executor_timeout_cancel_outcome(None)
        False
    """
    return str(getattr(outcome, "failure_detail", "") or "") == EXECUTOR_TIMEOUT_CANCEL_DETAIL


def _log_timeout_partial_tools(
    *,
    session_id: str,
    correlation_id: str,
    outcome: Any | None,
) -> None:
    """Emit gateway log when a tier-B timeout retained successful tool calls.

    Args:
        session_id (str): Active session id.
        correlation_id (str): Turn correlation id.
        outcome (Any | None): Partial ``BTurnOutcome`` from ``run_b_turn``.

    Examples:
        >>> _log_timeout_partial_tools(session_id="s", correlation_id="t", outcome=None)
    """
    successful = sorted(getattr(outcome, "successful_tools_called", frozenset()) or ())
    logger.info(
        "agent_turn.timeout_partial_tools session_id={} correlation_id={} successful_tools={}",
        session_id,
        correlation_id,
        successful,
    )


def _log_b_turn_pass(
    *,
    b_turn_kind: str,
    session_id: str,
    correlation_id: str,
    outcome: Any | None,
    no_answer_reason: str | None,
) -> None:
    """Emit one gateway log line summarizing a tier-B executor pass.

    Args:
        b_turn_kind (str): ``narrow``, ``summarize``, or ``full_index``.
        session_id (str): Active session id.
        correlation_id (str): Turn correlation id.
        outcome (Any | None): ``BTurnOutcome`` when the harness returned.
        no_answer_reason (str | None): Machine label when the pass raised or timed out.

    Examples:
        >>> _log_b_turn_pass(
        ...     b_turn_kind="narrow",
        ...     session_id="s",
        ...     correlation_id="t",
        ...     outcome=None,
        ...     no_answer_reason="timeout",
        ... )
    """
    if outcome is None:
        logger.info(
            "agent_turn.b_pass pass={} session_id={} correlation_id={} outcome=none reason={}",
            b_turn_kind,
            session_id,
            correlation_id,
            no_answer_reason,
        )
        return
    successful = sorted(getattr(outcome, "successful_tools_called", frozenset()) or ())
    logger.info(
        "agent_turn.b_pass pass={} session_id={} correlation_id={} status={} rounds={} "
        "successful_tools={} failure_detail={} reason={}",
        b_turn_kind,
        session_id,
        correlation_id,
        getattr(outcome, "status", None),
        getattr(outcome, "rounds_used", None),
        successful,
        getattr(outcome, "failure_detail", None),
        no_answer_reason,
    )


def _tier_b_full_index_retry_warranted(
    *,
    no_answer_reason: str | None,
    outcome: Any | None,
) -> bool:
    """Whether tier-B should run one widened-toolkit retry (Step 7c).

    Args:
        no_answer_reason (str | None): Machine label when the executor raised or timed out.
        outcome (Any | None): Tier-B outcome when the harness returned normally.

    Returns:
        bool: ``True`` for timeouts/exceptions/missing outcomes and for ``failed``
        outcomes that produced no user-visible report (e.g. tool errors without text).
        ``False`` for deterministic harness/parse faults that a retry cannot fix.

    Examples:
        >>> _tier_b_full_index_retry_warranted(no_answer_reason="timeout", outcome=None)
        True
        >>> _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=None)
        True
        >>> from types import SimpleNamespace
        >>> failed = SimpleNamespace(
        ...     status="failed",
        ...     final_messages=(SimpleNamespace(text="report"),),
        ...     had_tool_failures=True,
        ... )
        >>> _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=failed)
        True
        >>> parse_fault = SimpleNamespace(
        ...     status="failed",
        ...     final_messages=(),
        ...     had_tool_failures=False,
        ...     failure_detail="cd.decompose schema/parse failed",
        ... )
        >>> _tier_b_full_index_retry_warranted(no_answer_reason=None, outcome=parse_fault)
        False
    """
    if _is_deterministic_harness_failure(no_answer_reason=no_answer_reason, outcome=outcome):
        return False
    if _tier_b_tools_succeeded_without_answer(outcome):
        return False
    if no_answer_reason is not None or outcome is None:
        return True
    if getattr(outcome, "status", None) == "failed" and getattr(
        outcome, "had_tool_failures", False
    ):
        return True
    if getattr(outcome, "status", None) != "failed":
        return False
    return not any(
        (payload.text or "").strip() for payload in getattr(outcome, "final_messages", ())
    )


def _render_no_answer_message(reason: str, *, partial_progress: str | None = None) -> str:
    """Map a no-answer reason label to a user-facing line.

    Delegates to :func:`sevn.prompts.fallbacks.render_no_answer_message`.

    Args:
        reason (str): Machine-readable label like ``timeout`` or
            ``empty_output:status=ok``.
        partial_progress (str | None): Optional partial answer for budget-exhausted.

    Returns:
        str: Specific user message when the reason is known; the generic
        ``EXECUTOR_NO_ANSWER_FALLBACK`` otherwise.

    Examples:
        >>> "ran out of time" in _render_no_answer_message("timeout").lower()
        True
        >>> _render_no_answer_message("nonsense") == EXECUTOR_NO_ANSWER_FALLBACK
        True
    """
    return render_no_answer_message(reason, partial_progress=partial_progress)


# Per-tier executor wall-clock timeouts (seconds). Tier B is the interactive path; C/D
# decomposes/plans and can legitimately run longer. Configurable via
# ``gateway.budget.{tier_b_executor_timeout_s,tier_cd_executor_timeout_s,cascade_budget_s}``.
TIER_B_EXECUTOR_TIMEOUT_S = DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S
TIER_CD_EXECUTOR_TIMEOUT_S = DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S
# Cumulative cap across the cascade (initial B → summarize/full-index retry → C/D).
# Must exceed ``TIER_B_EXECUTOR_TIMEOUT_S`` so triager latency and one retry pass fit.
CASCADE_BUDGET_S = DEFAULT_CASCADE_BUDGET_S
if CASCADE_BUDGET_S <= TIER_B_EXECUTOR_TIMEOUT_S:
    msg = (
        "CASCADE_BUDGET_S must exceed TIER_B_EXECUTOR_TIMEOUT_S so triager latency "
        "and one retry pass fit"
    )
    raise ValueError(msg)


async def _emit_no_answer_fallback(
    *,
    router: ChannelRouter,
    channel: str,
    user_id: str,
    session_id: str,
    route_meta: dict[str, Any],
    trace: TraceSink,
    correlation_id: str,
    tier: str,
    reason: str,
    partial_progress: str | None = None,
) -> None:
    """Log the no-answer condition and send the human-friendly fallback once.

    Args:
        router (ChannelRouter): Gateway router used for outbound send.
        channel (str): Channel key (``telegram``, ``webchat``, ...).
        user_id (str): Destination user id.
        session_id (str): Owning session id.
        route_meta (dict[str, Any]): Outbound routing metadata (chat/topic ids).
        trace (TraceSink): Trace sink for the structured no-answer span.
        correlation_id (str): Per-turn correlation id used for the trace span.
        tier (str): ``A`` / ``B`` / ``C`` / ``D`` / ``?`` label for the affected tier.
        reason (str): Short machine label (``timeout``, ``exception``,
            ``empty_output:status=...``, ``unhandled_exception``).
        partial_progress (str | None): Optional partial answer for budget exhaustion.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_no_answer_fallback)
        True
    """
    logger.warning(
        "executor_no_answer tier={} reason={} session_id={}",
        tier,
        reason,
        session_id,
    )
    user_message = _render_no_answer_message(reason, partial_progress=partial_progress)
    await _emit_gateway_span(
        trace,
        kind="gateway.executor.no_answer",
        session_id=session_id,
        turn_id=correlation_id,
        status="fallback_sent",
        attrs={
            "tier": tier,
            "reason": reason,
            "typed": reason in _NO_ANSWER_MESSAGES or reason.startswith("empty_output"),
        },
    )
    try:
        await _route_assistant_text(
            router,
            channel,
            user_id,
            session_id,
            user_message,
            metadata=route_meta,
        )
    except Exception:
        logger.exception(
            "executor_no_answer_fallback_send_failed session_id={} tier={}",
            session_id,
            tier,
        )


def build_intro_extra_instructions(
    *,
    workspace: WorkspaceConfig,
    bootstrap_body: str | None,
) -> list[str]:
    """Build the ``extra_parts`` list for a first-session intro turn.

    Returns only the intro-specific block (``tier_b_intro_instructions``
    including the BOOTSTRAP body).  Orientation, repo-access, and
    self-architecture blocks are intentionally omitted per locked decision D5.

    This is a pure synchronous helper extracted so that W3 tests can assert
    on the exact ``extra_parts`` content without driving the full async
    ``build_agent_run_turn`` pipeline.

    Args:
        workspace (WorkspaceConfig): Operator workspace configuration (passed
            through to ``tier_b_intro_instructions``).
        bootstrap_body (str | None): Pre-loaded BOOTSTRAP.md markdown body, or
            ``None`` if the file is absent (use ``load_bootstrap_markdown`` to
            obtain it before calling).

    Returns:
        list[str]: Non-empty parts list — exactly one element on the current
        contract.  Join with ``"\\n\\n"`` to produce ``extra_instructions``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> parts = build_intro_extra_instructions(
        ...     workspace=WorkspaceConfig.minimal(), bootstrap_body="# BOOTSTRAP"
        ... )
        >>> len(parts) == 1
        True
    """
    return [
        tier_b_intro_instructions(
            workspace=workspace,
            bootstrap_body=bootstrap_body,
        )
    ]


def build_agent_run_turn(
    router: ChannelRouter,
    conn: sqlite3.Connection,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    trace: TraceSink,
    *,
    process_settings: ProcessSettings | None = None,
    tier_b_bundle_factory: Callable[[WorkspaceConfig], Awaitable[ResolvedTierBModel]] | None = None,
    runtime_bindings: RuntimeToolBindings | None = None,
    mcp_tool_definitions: tuple[ToolDefinition, ...] = (),
    enqueue_improve_job: object | None = None,
) -> RunTurnFn:
    """Return ``run_turn`` that routes Triager output to tier A/B executors (§2.6).

    When ``TRIAGER_ENABLED`` is false, skips ``triage_turn`` and passthroughs tier B.
    Tier C/D invoke ``run_cd_turn``; tier-B ``escalated`` re-enters C/D after optional re-Triage.
    When ``plan_approval.enabled`` is true, ``SqlitePlanGate`` blocks on Telegram callbacks.

    Args:
        router (ChannelRouter): Gateway router for ``route_outgoing``.
        conn (sqlite3.Connection): Open gateway SQLite handle.
        workspace (WorkspaceConfig): Parsed workspace configuration.
        layout (WorkspaceLayout): Resolved filesystem layout (tool spill paths).
        trace (TraceSink): Gateway trace sink.
        process_settings (ProcessSettings | None): Proxy URL source for tier-B transport.
        tier_b_bundle_factory (Callable | None): Test-only override for tier-B transport bundle.
        runtime_bindings (RuntimeToolBindings | None): Sandbox/MCP/integration hooks for
            ``build_session_registry`` (defaults to empty bindings when omitted).
        mcp_tool_definitions (tuple[ToolDefinition, ...]): MCP tool descriptors discovered at
            boot (from ``discover_mcp_tool_definitions``); passed as ``extra_mcp`` to
            ``build_session_registry`` each turn.  W3 folds this into the single bindings
            factory — keep the field here as the forward seam.
        enqueue_improve_job (object | None): Optional gateway-bound improve enqueue callable.

    Returns:
        RunTurnFn: Per-session dispatch callable wired at gateway boot.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(build_agent_run_turn)
        True
    """

    process = process_settings or ProcessSettings()
    bindings = runtime_bindings or RuntimeToolBindings()
    mcp_defs: tuple[ToolDefinition, ...] = mcp_tool_definitions
    plan_registry = PlanGateWaitRegistry()
    plan_handler = PlanGateCallbackHandler(conn, plan_registry)
    evo_registry = EvolutionApprovalWaitRegistry()
    evo_handler = EvolutionApprovalCallbackHandler(layout, evo_registry)
    qa_handler = QuickActionCallbackHandler(conn, router)
    menu_handler = MenuCallbackHandler(workspace, router)
    config_menu_handler = ConfigMenuHandler(workspace, router)
    core_handler = CoreCommandHandler(
        workspace=workspace,
        layout=layout,
        router=router,
        sessions=router._sessions,
    )
    platform_handler = PlatformCommandHandler(router=router)
    improve_handler: SelfImproveCommandHandler | None = None
    if enqueue_improve_job is not None:
        improve_handler = SelfImproveCommandHandler(
            workspace=workspace,
            layout=layout,
            router=router,
            enqueue_improve=enqueue_improve_job,  # type: ignore[arg-type]
        )
    file_issue_handler = FileIssueCommandHandler(
        workspace=workspace,
        layout=layout,
        router=router,
    )
    evolution_handler = EvolutionCommandHandler(
        workspace=workspace,
        layout=layout,
        router=router,
        conn=conn,
    )
    evolution_chat_bridge = EvolutionChatBridge(
        workspace=workspace,
        layout=layout,
        router=router,
        conn=conn,
    )
    diagnostic_handler = DiagnosticCommandHandler(
        workspace=workspace,
        layout=layout,
        router=router,
    )
    command_invoker = MenuCommandInvoker(
        router=router,
        core_handler=core_handler,
        config_menu_handler=config_menu_handler,
        menu_handler=menu_handler,
    )
    config_menu_handler._command_invoker = command_invoker
    menu_handler._command_invoker = command_invoker
    action_router = MenuActionRouter(
        workspace=workspace,
        router=router,
        conn=conn,
        content_root=layout.content_root,
        sevn_json_path=layout.sevn_json_path,
    )
    form_handler = MenuFormHandler(
        workspace=workspace,
        router=router,
        conn=conn,
        content_root=layout.content_root,
        sevn_json_path=layout.sevn_json_path,
    )
    from sevn.gateway.commands.file_link_callback_handler import FileLinkCallbackHandler

    file_link_handler = FileLinkCallbackHandler(
        router=router,
        content_root=layout.content_root,
    )
    router._plan_gate_registry = plan_registry
    router._plan_gate_callback_handler = plan_handler
    router._evolution_approval_registry = evo_registry
    router._evolution_approval_callback_handler = evo_handler
    router._quick_action_callback_handler = qa_handler
    router._menu_callback_handler = menu_handler
    router._config_menu_handler = config_menu_handler
    router._core_command_handler = core_handler
    router._platform_command_handler = platform_handler
    router._evolution_command_handler = evolution_handler
    router._diagnostic_command_handler = diagnostic_handler
    router._menu_action_router = action_router
    router._menu_form_handler = form_handler
    if router._dashboard_pin_publisher is None:
        router._dashboard_pin_publisher = DashboardPinPublisher()
    _orig_route_incoming = router.route_incoming

    async def _route_incoming_with_menu(msg: IncomingMessage) -> None:
        """Intercept dispatcher bypass handlers before generic routing."""
        from sevn.gateway.channel_router import _scope_key

        session_id = await router._sessions.ensure_session(
            scope_key=_scope_key(msg),
            channel=msg.channel,
            user_id=msg.user_id,
        )

        async def _record_command() -> None:
            # Menu-intercept commands are handled synchronously by the wrapped
            # handler; no agent turn is dispatched, so no turn correlation id
            # exists. Use the sentinel — these rows live outside any turn.
            await router._sessions.add_message(
                session_id,
                role="user",
                kind="command",
                content=msg.text,
                visible_to_llm=0,
                status="sent",
                turn_id=SYSTEM_TURN_ID,
            )

        if config_menu_handler.matches(msg) or config_menu_handler.matches_slash(msg):
            await _record_command()
            if config_menu_handler.matches_slash(msg):
                await config_menu_handler.handle_slash(msg, session_id=session_id)
            else:
                await config_menu_handler.handle(msg, session_id=session_id)
            return
        if form_handler.matches(msg):
            await _record_command()
            await form_handler.handle(msg, session_id=session_id)
            return
        if file_link_handler.matches(msg):
            await _record_command()
            reply = await file_link_handler.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
            return
        if action_router.matches(msg):
            await _record_command()
            reply = await action_router.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
            return
        if menu_handler.matches(msg) or menu_handler.matches_slash(msg):
            await _record_command()
            if menu_handler.matches_slash(msg):
                await menu_handler.handle_slash(msg, session_id=session_id)
            else:
                await menu_handler.handle(msg, session_id=session_id)
            return
        if improve_handler is not None and improve_handler.matches_slash(msg):
            await _record_command()
            reply = await improve_handler.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
            return
        if file_issue_handler.matches_slash(msg):
            await _record_command()
            reply = await file_issue_handler.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
            return
        if evolution_handler.matches_slash(msg):
            await _record_command()
            reply = await evolution_handler.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
            return
        if evolution_chat_bridge.matches_nl(msg):
            await _record_command()
            reply = await evolution_chat_bridge.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
            return
        if diagnostic_handler.matches_slash(msg):
            await _record_command()
            chunks = await diagnostic_handler.handle(msg, session_id=session_id)
            adapter = router._adapters.get(msg.channel)
            if adapter is not None and chunks:
                from sevn.gateway.channel_router import (
                    OutgoingMessage,
                    _telegram_reply_metadata,
                )

                base_meta = dict(_telegram_reply_metadata(msg))
                base_meta.setdefault("parse_mode", "HTML")
                for chunk in chunks:
                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=chunk,
                            session_id=session_id,
                            metadata=dict(base_meta),
                        ),
                    )
            return
        if platform_handler.matches_slash(msg):
            owner = router._resolve_owner_flag(msg)
            if not router.slash_command_allowed(msg, is_owner=owner):
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text="You are not allowed to run that command.",
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
                return
            await _record_command()
            reply = platform_handler.handle(msg, is_owner=owner)
            adapter = router._adapters.get(msg.channel)
            if adapter is not None and reply:
                from sevn.gateway.channel_router import (
                    OutgoingMessage,
                    _telegram_reply_metadata,
                )

                await adapter.send(
                    OutgoingMessage(
                        channel=msg.channel,
                        user_id=msg.user_id,
                        text=reply,
                        session_id=session_id,
                        metadata=dict(_telegram_reply_metadata(msg)),
                    ),
                )
            return
        if core_handler.matches_slash(msg):
            owner = router._resolve_owner_flag(msg)
            if not router.slash_command_allowed(msg, is_owner=owner):
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text="You are not allowed to run that command.",
                            session_id=session_id,
                            metadata=dict(_telegram_reply_metadata(msg)),
                        ),
                    )
                return
            await _record_command()
            if (msg.text or "").strip().startswith("/config"):
                await config_menu_handler.handle_slash(msg, session_id=session_id)
                return
            reply = await core_handler.handle(msg, session_id=session_id)
            if reply:
                adapter = router._adapters.get(msg.channel)
                if adapter is not None:
                    from sevn.gateway.channel_router import (
                        OutgoingMessage,
                        _telegram_reply_metadata,
                    )

                    out_meta = dict(_telegram_reply_metadata(msg))
                    mid = msg.metadata.get("message_id") if isinstance(msg.metadata, dict) else None
                    if isinstance(mid, int):
                        out_meta["reply_to_message_id"] = mid
                    await adapter.send(
                        OutgoingMessage(
                            channel=msg.channel,
                            user_id=msg.user_id,
                            text=reply,
                            session_id=session_id,
                            metadata=out_meta,
                        ),
                    )
            return
        await _orig_route_incoming(msg)

    router.route_incoming = _route_incoming_with_menu  # type: ignore[method-assign]

    async def _run(session_id: str, correlation_id: str) -> None:
        # Pick up /config toggles (e.g. channels.telegram.show_routing) without gateway restart.
        workspace = router._workspace
        tier_b_timeout_s = tier_b_executor_timeout_s(workspace)
        tier_cd_timeout_s = tier_cd_executor_timeout_s(workspace)
        # Cumulative wall-clock cap across the cascade (`PROBLEMS.md` Priority 1(e)).
        budget = CascadeBudget(cascade_budget_s(workspace))

        sess = await asyncio.to_thread(load_session_row, conn, session_id)
        if sess is None:
            logger.error("agent_turn missing session session_id={}", session_id)
            return
        superseded_ids = await asyncio.to_thread(
            supersede_awaiting_for_session,
            conn,
            session_id=session_id,
        )
        if superseded_ids:
            plan_registry.supersede_all(superseded_ids)
        # Wave 3 (CONVERSATION_REVIEW_2026-05-28.md §A15 + §A16): quick-action
        # regen stages the ORIGINAL user message (and the assistant bubble to
        # edit) via SessionManager.set_regen_target so the regen turn re-asks
        # the original request and reuses the existing message instead of
        # stacking a fresh triager opener on top of the prior reply.
        replay_target = router._sessions.take_replay_target(session_id)
        replay_attrs: dict[str, str] = {}
        regen_target = router._sessions.take_regen_target(session_id)
        regen_edit_message_id: int | None = None
        regen_suggested_tier: str | None = None
        if replay_target is not None and replay_target[0].strip():
            user_text = replay_target[0]
            replay_attrs = {
                "replay.of_turn_id": replay_target[1],
                "replay.kind": "dashboard_rerun",
            }
            logger.info(
                "agent_turn replay_target_applied session_id={} origin_turn_id={} replay_job_id={} text_len={}",
                session_id,
                replay_target[1],
                replay_target[2],
                len(user_text),
            )
        elif regen_target is not None and regen_target[0].strip():
            user_text = regen_target[0]
            regen_edit_message_id = regen_target[2]
            regen_suggested_tier = regen_target[3]
            logger.info(
                "agent_turn regen_target_applied session_id={} origin_turn_id={} edit_mid={} text_len={}",
                session_id,
                regen_target[1],
                regen_edit_message_id,
                len(user_text),
            )
        else:
            latest_text = await asyncio.to_thread(_latest_user_message_text, conn, session_id)
            backref_target = _resolve_retry_back_reference(
                conn,
                session_id,
                latest_text=latest_text,
            )
            if backref_target is not None:
                logger.info(
                    "agent_turn backref_retry_resolved session_id={} phrase={!r} target_len={}",
                    session_id,
                    latest_text,
                    len(backref_target),
                )
                user_text = backref_target
            else:
                # P1 (cancel-mode collapse): a burst of quick messages is
                # superseded into this one surviving turn; the executor already
                # sees all of them, so merge the pending user lines here too and
                # let triage select the union of tools they need
                # (`specs/17-gateway.md` §2.5). Falls back to the single latest
                # line when nothing else is pending.
                user_text = await asyncio.to_thread(_pending_user_messages_text, conn, session_id)
                if user_text.strip() != latest_text.strip():
                    logger.info(
                        "agent_turn pending_burst_merged session_id={} merged_len={} latest_len={}",
                        session_id,
                        len(user_text),
                        len(latest_text),
                    )
        if not user_text.strip():
            logger.warning("agent_turn empty user text session_id={}", session_id)
            return
        turn_span_id = uuid.uuid4().hex
        await _emit_gateway_span(
            trace,
            kind="gateway.turn.start",
            session_id=session_id,
            turn_id=correlation_id,
            status="started",
            attrs={
                "operator_message": user_text,
                "channel": sess.channel,
                "user_id": sess.user_id,
                **replay_attrs,
            },
            span_id=turn_span_id,
        )
        if user_text.strip().lower() in ("skip intro", "skip introduction"):
            await asyncio.to_thread(mark_intro_state, conn, session_id, "skipped")
        route_meta = await asyncio.to_thread(
            _outbound_routing_metadata,
            conn,
            session_id,
            sess.channel,
            sess.user_id,
        )
        triage_ctx = triage_context_from_session(
            conn,
            session_id,
            workspace,
            user_text,
            layout=layout,
            turn_id=correlation_id,
            channel=sess.channel,
            user_id=sess.user_id,
        )
        first_session_intro = triage_ctx.is_first_session
        from sevn.onboarding.seed import resolve_agent_display_name

        agent_name = resolve_agent_display_name(workspace.model_dump())
        bootstrap_active = await asyncio.to_thread(
            bootstrap_capture_active,
            conn,
            session_id,
            workspace=workspace,
            content_root=layout.content_root,
            agent_name=agent_name,
            channel=sess.channel,
            user_id=sess.user_id,
        )
        intro_outbound_marked = False
        if bootstrap_active and await _bootstrap_capture_after_turn(
            bootstrap_active=True,
            content_root=layout.content_root,
            user_text=user_text,
            agent_name=agent_name,
            conn=conn,
            session_id=session_id,
            write=False,  # no pre-triage heuristic write; tier-B may capture structured answers
        ):
            intro_outbound_marked = True
            bootstrap_active = await asyncio.to_thread(
                bootstrap_capture_active,
                conn,
                session_id,
                workspace=workspace,
                content_root=layout.content_root,
                agent_name=agent_name,
                channel=sess.channel,
                user_id=sess.user_id,
            )
            triage_ctx = triage_ctx.model_copy(
                update={"bootstrap_capture_active": bootstrap_active},
            )
        session_exe, session_tool_set = await asyncio.to_thread(
            build_session_registry,
            workspace_config=workspace,
            runtime_bindings=bindings,
            extra_mcp=mcp_defs,
            workspace_root=layout.content_root,
            layout=layout,
            trace_sink=trace,
            include_bootstrap_tools=bootstrap_active,
        )

        def _sync_tools_md_catalog() -> None:
            from sevn.workspace.tools_md import sync_tools_md

            sync_tools_md(
                layout.content_root,
                session_tool_set,
                agent_name=agent_name,
            )

        await asyncio.to_thread(_sync_tools_md_catalog)
        registry = registry_snapshot_from_tool_set(
            session_tool_set,
            workspace=workspace,
            content_root=layout.content_root,
        )
        routing_footer_sent = False
        show_routing = sess.channel == "telegram"
        if show_routing:
            from sevn.gateway.routing_footer import telegram_show_routing_enabled

            show_routing = telegram_show_routing_enabled(router._workspace)
        session_view = session_view_from_session(
            conn,
            session_id,
            channel=sess.channel,
            user_id=sess.user_id,
        )
        turn_media_summaries = await asyncio.to_thread(
            load_turn_media_summaries,
            conn,
            session_id,
            correlation_id,
        )
        attachment_hints = attachment_hints_for_triager(turn_media_summaries)
        incoming = ApprovedUserTurn(text=user_text, attachment_descriptors=attachment_hints)
        triage_passthrough = not is_triager_enabled()
        triager_ms: int | None = None
        if triage_passthrough:
            triage = passthrough_triage_result()
            await _emit_gateway_span(
                trace,
                kind="gateway.triage.completed",
                session_id=session_id,
                turn_id=correlation_id,
                status="passthrough",
                attrs={"triager_enabled": False, "complexity": str(triage.complexity)},
            )
        else:
            try:
                triage_started_ns = time_ns()
                triage = await triage_turn(
                    workspace=workspace,
                    session=session_view,
                    incoming=incoming,
                    registry_snapshot=registry,
                    triage_context=triage_ctx,
                    content_root=layout.content_root,
                    trace=trace,
                    turn_span_id=turn_span_id,
                )
                triager_ms = max(1, int((time_ns() - triage_started_ns) / 1_000_000))
            except TriagerUnavailable:
                logger.exception("agent_turn triager unavailable session_id={}", session_id)
                if bootstrap_active:
                    await _bootstrap_capture_after_turn(
                        bootstrap_active=True,
                        content_root=layout.content_root,
                        user_text=user_text,
                        agent_name=agent_name,
                        conn=conn,
                        session_id=session_id,
                        write=True,
                    )
                await _route_assistant_text(
                    router,
                    sess.channel,
                    sess.user_id,
                    session_id,
                    "Sorry — message routing is unavailable right now.",
                    metadata=route_meta,
                )
                return
            await asyncio.to_thread(
                persist_triage_decision,
                conn,
                workspace=workspace,
                session_id=session_id,
                turn_id=correlation_id,
                triage=triage,
                registry_version=registry.registry_version,
                personality_version=triage_ctx.personality_version,
            )
            await _emit_gateway_span(
                trace,
                kind="gateway.triage.completed",
                session_id=session_id,
                turn_id=correlation_id,
                status="completed",
                attrs={"complexity": str(triage.complexity), "disregard": triage.disregard},
            )
        if regen_suggested_tier in ("C", "D"):
            forced = ComplexityTier.C if regen_suggested_tier == "C" else ComplexityTier.D
            if triage.complexity != forced:
                logger.info(
                    "agent_turn.regen_tier_preserved session_id={} turn_id={} "
                    "suggested_tier={} triager_complexity={}",
                    session_id,
                    correlation_id,
                    regen_suggested_tier,
                    triage.complexity,
                )
                triage = triage.model_copy(update={"complexity": forced, "first_message": ""})
        if triage.disregard:
            await _emit_gateway_span(
                trace,
                kind="gateway.triage.disregard",
                session_id=session_id,
                turn_id=correlation_id,
                status="completed",
                attrs={},
            )
            return
        from sevn.agent.capability_reply import (
            compose_list_skills_reply,
            compose_list_tools_reply,
            is_list_skills_message,
            is_list_tools_message,
        )
        from sevn.agent.identity_reply import compose_identity_reply, is_pure_identity_message

        if is_pure_identity_message(user_text):
            identity_reply = compose_identity_reply(
                layout.content_root,
                agent_display_name=agent_name,
            )
            if identity_reply:
                intent_label = "NEW_REQUEST"
                tier_label = "A"
                await asyncio.to_thread(
                    record_turn_start,
                    conn,
                    turn_id=correlation_id,
                    session_id=session_id,
                    intent=intent_label,
                    tier=tier_label,
                    confidence=1.0,
                    model_id=None,
                )
                await _route_assistant_text(
                    router,
                    sess.channel,
                    sess.user_id,
                    session_id,
                    identity_reply,
                    metadata=route_meta,
                    outbound_phase="final",
                )
                await asyncio.to_thread(
                    record_turn_finished,
                    conn,
                    turn_id=correlation_id,
                    status="completed",
                )
                return

        capability_reply: str | None = None
        if is_list_skills_message(user_text):
            capability_reply = compose_list_skills_reply(
                session_tool_set.skill_descriptions,
                skill_inventory=session_tool_set.skill_inventory,
            )
        elif is_list_tools_message(user_text):
            capability_reply = compose_list_tools_reply(session_tool_set.native)
        if capability_reply is not None:
            await asyncio.to_thread(
                record_turn_start,
                conn,
                turn_id=correlation_id,
                session_id=session_id,
                intent="NEW_REQUEST",
                tier="A",
                confidence=1.0,
                model_id=None,
            )
            await _route_assistant_text(
                router,
                sess.channel,
                sess.user_id,
                session_id,
                capability_reply,
                metadata=route_meta,
                outbound_phase="final",
            )
            await asyncio.to_thread(
                record_turn_finished,
                conn,
                turn_id=correlation_id,
                status="completed",
            )
            return
        # §7 (`PROBLEMS.md`): record routing classifier output into
        # ``gateway_turn_metadata`` so the per-channel renderer can read
        # it back when the ``show_intent_footer`` toggle is on, instead of
        # leaking the ``_intent=… · tier=… · conf=…_`` line into the
        # persisted message content.
        intent_label = (
            triage.intent.value if hasattr(triage.intent, "value") else str(triage.intent)
        )
        tier_label = (
            triage.complexity.value
            if hasattr(triage.complexity, "value")
            else str(triage.complexity)
        )
        await asyncio.to_thread(
            record_turn_start,
            conn,
            turn_id=correlation_id,
            session_id=session_id,
            intent=intent_label,
            tier=tier_label,
            confidence=float(triage.confidence),
            model_id=None,
        )
        first = (triage.first_message or "").strip()
        first_task: asyncio.Task[None] | None = None
        had_triager_first = False
        if (
            first
            and router._sessions.consume_cancel_supersession(
                session_id,
                within_s=_CANCEL_INTERRUPT_SUPPRESS_S,
            )
            and _is_triager_opener_ack(first)
        ):
            logger.info(
                "agent_turn.cancel_opener_suppressed session_id={} turn_id={} opener_len={}",
                session_id,
                correlation_id,
                len(first),
            )
            first = ""
        if first:
            if triage.complexity == ComplexityTier.A:
                first_phase = "final"
            else:
                # Tier B/C/D: Triager opening line stays on Telegram; executor streams separately.
                first_phase = "persist"
                had_triager_first = True
                if first_session_intro:
                    await asyncio.to_thread(mark_intro_state, conn, session_id, "in_flight")
            outbound_first, applied = _apply_routing_footer_once(
                first,
                triage=triage,
                triager_ms=triager_ms,
                enabled=show_routing,
                sent=routing_footer_sent,
            )
            routing_footer_sent = routing_footer_sent or applied
            # Wave 3 §A16: when a quick-action regen staged an
            # ``edit_message_id``, reuse the prior assistant bubble for the
            # triager opener so the regen turn does not stack a fresh ack.
            first_meta = dict(route_meta)
            if regen_edit_message_id is not None:
                first_meta["edit_message_id"] = regen_edit_message_id
            first_task = asyncio.create_task(
                _route_assistant_text(
                    router,
                    sess.channel,
                    sess.user_id,
                    session_id,
                    outbound_first,
                    metadata=first_meta,
                    outbound_phase=first_phase,
                )
            )
        if triage.complexity == ComplexityTier.A:
            if first_task is not None:
                await first_task
            if await _bootstrap_capture_after_turn(
                bootstrap_active=bootstrap_active,
                content_root=layout.content_root,
                user_text=user_text,
                agent_name=agent_name,
                conn=conn,
                session_id=session_id,
            ):
                intro_outbound_marked = True
            return
        if triage.complexity in (ComplexityTier.C, ComplexityTier.D):
            if first_task is not None:
                await first_task
            await _run_cd_dispatch(
                router=router,
                conn=conn,
                workspace=workspace,
                layout=layout,
                trace=trace,
                session_id=session_id,
                correlation_id=correlation_id,
                turn_span_id=turn_span_id,
                sess_channel=sess.channel,
                sess_user_id=sess.user_id,
                triage=triage,
                user_text=user_text,
                route_meta=route_meta,
                process=process,
                bindings=bindings,
                mcp_tool_definitions=mcp_defs,
                plan_registry=plan_registry,
                had_triager_first=had_triager_first,
                timeout_s=budget.clamp(tier_cd_timeout_s),
            )
            if await _bootstrap_capture_after_turn(
                bootstrap_active=bootstrap_active,
                content_root=layout.content_root,
                user_text=user_text,
                agent_name=agent_name,
                conn=conn,
                session_id=session_id,
            ):
                intro_outbound_marked = True
            return
        if triage.complexity != ComplexityTier.B:
            if first_task is not None:
                await first_task
            logger.warning(
                "agent_turn unknown complexity session_id={} complexity={}",
                session_id,
                triage.complexity,
            )
            await _route_assistant_text(
                router,
                sess.channel,
                sess.user_id,
                session_id,
                TIER_UNSUPPORTED_USER_MESSAGE,
                metadata=route_meta,
            )
            return
        if tier_b_bundle_factory is not None:
            bundle = await tier_b_bundle_factory(workspace)
        else:
            bundle = _resolve_tier_b_bundle(workspace, process)
        exe, tool_set = session_exe, session_tool_set
        if first_task is not None:
            await first_task
        steer_buffer = _steer_buffer_for(router, session_id)
        channel_adapter = router.adapter_named(sess.channel)
        # Priority 2 (`PROBLEMS.md`): both ``stream`` and ``two_message_finally`` place a
        # "…" placeholder for the tier-B answer *before* the executor runs. Failure paths
        # finalize it exactly once. In ``stream`` mode the executor additionally pipes
        # accumulated answer text into the placeholder via ``finalizer.stream_update``;
        # the final ``finalize(success, …)`` then writes the authoritative text.
        finalizer: TierBAnswerFinalizer | None = None
        answer_mode = tier_b_answer_mode(workspace)
        if answer_mode in ("two_message_finally", "stream") and channel_adapter is not None:
            finalizer = TierBAnswerFinalizer(
                router=router,
                adapter=channel_adapter,
                channel=sess.channel,
                user_id=sess.user_id,
                session_id=session_id,
                turn_id=correlation_id,
                metadata=dict(route_meta),
            )
            await finalizer.place_placeholder()
        streaming_sink = (
            finalizer.stream_update if finalizer is not None and answer_mode == "stream" else None
        )
        if first_session_intro and streaming_sink is not None:
            logger.info(
                "agent_turn.intro_streaming_disabled channel={} session_id={} turn_id={}",
                sess.channel,
                session_id,
                correlation_id,
            )
            streaming_sink = None
        intro_max_output_tokens = (
            first_session_intro_max_output_tokens(
                workspace,
                model_id=bundle.model_id,
                content_root=layout.content_root,
            )
            if first_session_intro
            else None
        )
        if answer_mode == "stream":
            if streaming_sink is not None:
                logger.debug(
                    "agent_turn.streaming_sink_wired channel={} session_id={} turn_id={}",
                    sess.channel,
                    session_id,
                    correlation_id,
                )
            else:
                sink_skip_reason = (
                    "no_channel_adapter" if channel_adapter is None else "finalizer_not_constructed"
                )
                logger.info(
                    "agent_turn.streaming_sink_none channel={} session_id={} turn_id={} reason={}",
                    sess.channel,
                    session_id,
                    correlation_id,
                    sink_skip_reason,
                )
        extra_parts: list[str] = []
        bootstrap = await asyncio.to_thread(
            load_bootstrap_markdown_cached,
            layout.content_root,
        )
        if first_session_intro:
            extra_parts.extend(
                build_intro_extra_instructions(
                    workspace=workspace,
                    bootstrap_body=bootstrap,
                )
            )
            logger.debug(
                "agent_turn.intro_extra_instructions_trimmed channel={} session_id={} turn_id={}",
                sess.channel,
                session_id,
                correlation_id,
            )
        else:
            if bootstrap_active:
                extra_parts.append(
                    bootstrap_capture_instructions(
                        workspace=workspace,
                        bootstrap_body=bootstrap,
                        content_root=layout.content_root,
                    ),
                )
            orient = orientation_block_for_workspace(
                workspace,
                content_root=layout.content_root,
                intent=infer_orientation_intent(user_text),
            )
            if orient.strip():
                extra_parts.append(orient)
            if is_repo_code_intent_message(user_text):
                extra_parts.append(tier_b_self_architecture_inject())
            if is_routing_footer_query(user_text):
                extra_parts.append(tier_b_routing_footer_inject())
            extra_parts.append(tier_b_repo_access_prompt(workspace, layout.content_root))
        extra_instructions = "\n\n".join(p for p in extra_parts if p.strip())

        tier_b_tool_context = _tool_context_for_turn(
            session_id=session_id,
            correlation_id=correlation_id,
            workspace=workspace,
            layout=layout,
            trace=trace,
            tool_set=tool_set,
            channel=sess.channel,
            channel_adapter=channel_adapter,
            channel_router=router,
            outbound_user_id=sess.user_id,
            outbound_metadata=route_meta,
            runtime_bindings=bindings,
            plugin_hooks=_plugin_hooks_from_router(router),
            turn_span_id=turn_span_id,
        )

        # Retry-storm guard (`specs/17-gateway.md` §3.4): the narrow first pass keeps the
        # full transcript, but summarize / full-index retries — which fail on behaviour, not
        # missing context — get a windowed transcript so a failed turn stops re-sending the
        # whole history on every pass and blowing the token budget ~5x.
        retry_windowed_turns, retry_windowed_rows = window_transcript(
            list(triage_ctx.transcript_turns),
            list(triage_ctx.transcript_rows),
            max_turns=DEFAULT_TIER_B_RETRY_HISTORY_TURNS,
        )

        async def _execute_tier_b_pass(
            *,
            pass_kind: str,
            reason_suffix: str,
            raise_event: str,
            max_rounds: int | None,
            streaming_sink: Any | None,
            emit_pass_log: bool,
            windowed: bool = False,
        ) -> tuple[Any | None, str | None]:
            pass_transcript_turns = (
                retry_windowed_turns if windowed else list(triage_ctx.transcript_turns)
            )
            pass_transcript_rows = (
                retry_windowed_rows if windowed else list(triage_ctx.transcript_rows)
            )
            pass_outcome: Any | None = None
            pass_no_answer_reason: str | None = None
            try:
                pass_outcome = await asyncio.wait_for(
                    run_b_turn(
                        workspace=workspace,
                        session=SessionHandle(session_id=session_id),
                        turn_id=correlation_id,
                        triage=triage,
                        incoming_text=user_text,
                        tool_set=tool_set,
                        body_cache=LoadedBodyCache(capacity=8),
                        tool_executor=exe,
                        transport_bundle=bundle,
                        trace=trace,
                        steer_buffer=steer_buffer,
                        operator_local_date=triage_ctx.operator_local_date,
                        extra_instructions=extra_instructions,
                        tool_context=tier_b_tool_context,
                        max_rounds=max_rounds,
                        max_output_tokens=intro_max_output_tokens,
                        first_session_intro=first_session_intro,
                        streaming_sink=streaming_sink,
                        transcript_turns=pass_transcript_turns,
                        transcript_rows=pass_transcript_rows,
                        return_partial_on_cancel=True,
                    ),
                    timeout=budget.clamp(tier_b_timeout_s),
                )
                pass_no_answer_reason = None
            except TimeoutError:
                pass_no_answer_reason = f"timeout{reason_suffix}"
            except Exception:
                logger.exception(
                    "{} session_id={} correlation_id={}",
                    raise_event,
                    session_id,
                    correlation_id,
                )
                pass_no_answer_reason = f"exception{reason_suffix}"
            if _is_executor_timeout_cancel_outcome(pass_outcome):
                pass_no_answer_reason = f"timeout{reason_suffix}"
                _log_timeout_partial_tools(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    outcome=pass_outcome,
                )
            if emit_pass_log:
                _log_b_turn_pass(
                    b_turn_kind=pass_kind,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    outcome=pass_outcome,
                    no_answer_reason=pass_no_answer_reason,
                )
            return pass_outcome, pass_no_answer_reason

        outcome = None
        no_answer_reason: str | None = None
        # If the previous turn for this session ended in the tier-C-unavailable retry path,
        # start tier B directly with the expanded budget to skip the wasted first attempt
        # (`specs/14-executor-tier-b.md` §5; transcript-review item #10).
        prior_needed_expanded = session_id in router._sessions_needing_expanded_budget
        initial_max_rounds = tier_b_rounds_expanded(workspace) if prior_needed_expanded else None
        if prior_needed_expanded:
            router._sessions_needing_expanded_budget.discard(session_id)
        outcome, no_answer_reason = await _execute_tier_b_pass(
            pass_kind="narrow",  # nosec B106
            reason_suffix="",
            raise_event="tier_b_executor_raised",
            max_rounds=initial_max_rounds,
            streaming_sink=streaming_sink,
            emit_pass_log=True,
        )
        retry_warranted = _tier_b_full_index_retry_warranted(
            no_answer_reason=no_answer_reason,
            outcome=outcome,
        )
        logger.info(
            "agent_turn.retry_decision session_id={} correlation_id={} retry_warranted={} "
            "summarize_warranted={}",
            session_id,
            correlation_id,
            retry_warranted,
            _tier_b_tools_succeeded_without_answer(outcome),
        )
        if retry_warranted and first_session_intro:
            logger.info(
                "agent_turn.intro_full_index_retry_skipped session_id={} turn_id={} reason={}",
                session_id,
                correlation_id,
                no_answer_reason or "missing_outcome",
            )
            retry_warranted = False
        if _tier_b_tools_succeeded_without_answer(outcome):
            successful = frozenset(
                getattr(outcome, "successful_tools_called", frozenset()),
            )
            if steer_buffer is not None:
                steer_buffer.inject_pending(steer_for_summarize_after_fetch(successful))
            logger.info(
                "agent_turn.summarize_retry session_id={} correlation_id={} tools={}",
                session_id,
                correlation_id,
                sorted(successful),
            )
            if not budget.exhausted():
                summarize_outcome, summarize_reason = await _execute_tier_b_pass(
                    pass_kind="summarize",  # nosec B106
                    reason_suffix="_summarize_retry",
                    raise_event="tier_b_summarize_retry_raised",
                    max_rounds=initial_max_rounds,
                    # W6 / 7b8454: summarize is a single final answer — do not
                    # re-tap progressive streaming after a partial first pass.
                    streaming_sink=None,
                    emit_pass_log=False,
                    windowed=True,
                )
                if summarize_outcome is not None:
                    outcome = summarize_outcome
                if summarize_reason is not None:
                    no_answer_reason = summarize_reason
                elif summarize_outcome is not None:
                    no_answer_reason = None
            _log_b_turn_pass(
                b_turn_kind="summarize",
                session_id=session_id,
                correlation_id=correlation_id,
                outcome=outcome,
                no_answer_reason=no_answer_reason,
            )
            retry_warranted = _tier_b_full_index_retry_warranted(
                no_answer_reason=no_answer_reason,
                outcome=outcome,
            )
        if retry_warranted:
            logger.info(
                "agent_turn.full_index_retry_start session_id={} correlation_id={} reason={}",
                session_id,
                correlation_id,
                no_answer_reason or "missing_outcome",
            )
            # Step 7c (`PROBLEMS.md` Priority 1(e)): exactly one retry with the full
            # skills/INDEX exposed before escalating to tier C/D. Lets the executor
            # self-rescue when the triager's narrow allowlist didn't have the right
            # tool or a tool error left no answer. If budget is already exhausted,
            # report partial progress and invite retry — never a bare giveup line.
            if budget.exhausted():
                partial = _collect_partial_progress(finalizer=finalizer, outcome=outcome)
                budget_msg = format_cascade_budget_exhausted_message(partial)
                if finalizer is not None:
                    await finalizer.finalize(
                        status="timeout",
                        text=budget_msg,
                    )
                    return
                await _emit_no_answer_fallback(
                    router=router,
                    channel=sess.channel,
                    user_id=sess.user_id,
                    session_id=session_id,
                    route_meta=route_meta,
                    trace=trace,
                    correlation_id=correlation_id,
                    tier="B",
                    reason="cascade_budget_exhausted",
                    partial_progress=partial,
                )
                return
            outcome, no_answer_reason = await _run_full_index_retry(
                workspace=workspace,
                layout=layout,
                bundle=bundle,
                tool_set=tool_set,
                exe=exe,
                bindings=bindings,
                router=router,
                trace=trace,
                steer_buffer=steer_buffer,
                channel_adapter=channel_adapter,
                turn_span_id=turn_span_id,
                session_id=session_id,
                correlation_id=correlation_id,
                sess_channel=sess.channel,
                sess_user_id=sess.user_id,
                route_meta=route_meta,
                triage=triage,
                user_text=user_text,
                extra_instructions=extra_instructions,
                streaming_sink=streaming_sink,
                finalizer=finalizer,
                first_attempt_reason=no_answer_reason or "missing_outcome",
                budget=budget,
                # Windowed history (retry-storm guard): the full-index retry fails on
                # behaviour, not missing context, so it does not re-send all ~33 turns.
                transcript_turns=retry_windowed_turns,
                transcript_rows=retry_windowed_rows,
                operator_local_date=triage_ctx.operator_local_date,
            )
            _log_b_turn_pass(
                b_turn_kind="full_index",
                session_id=session_id,
                correlation_id=correlation_id,
                outcome=outcome,
                no_answer_reason=no_answer_reason,
            )
            if outcome is None:
                # Retry also failed → escalate to tier C.
                if budget.exhausted() and finalizer is not None:
                    partial = _collect_partial_progress(finalizer=finalizer, outcome=outcome)
                    await finalizer.finalize(
                        status="timeout",
                        text=format_cascade_budget_exhausted_message(partial),
                    )
                    return
                if finalizer is not None and not finalizer.is_finalized:
                    await finalizer.stream_update(
                        "Escalating to tier C — this is taking longer than expected.",
                    )
                synthetic_esc = EscalationRequest(
                    reason=f"tier_b_double_failure:{no_answer_reason}",
                    target_tier="C",
                    user_visible_message="",
                )
                cd_triage_synth = _synthetic_escalation_triage(synthetic_esc)
                await _run_cd_dispatch(
                    router=router,
                    conn=conn,
                    workspace=workspace,
                    layout=layout,
                    trace=trace,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    turn_span_id=turn_span_id,
                    sess_channel=sess.channel,
                    sess_user_id=sess.user_id,
                    triage=cd_triage_synth,
                    user_text=user_text,
                    route_meta=route_meta,
                    process=process,
                    bindings=bindings,
                    mcp_tool_definitions=mcp_defs,
                    plan_registry=plan_registry,
                    had_triager_first=had_triager_first,
                    finalizer=finalizer,
                    timeout_s=budget.clamp(tier_cd_timeout_s),
                )
                return
            # Retry produced an outcome — fall through to the regular outcome
            # processing path below.
        elif first_session_intro and (no_answer_reason is not None or outcome is None):
            intro_fail_reason = "first_session_intro_failure"
            fail_text = _render_no_answer_message(intro_fail_reason)
            if finalizer is not None and not finalizer.is_finalized:
                await finalizer.finalize(status="error", text=fail_text)
                return
            await _emit_no_answer_fallback(
                router=router,
                channel=sess.channel,
                user_id=sess.user_id,
                session_id=session_id,
                route_meta=route_meta,
                trace=trace,
                correlation_id=correlation_id,
                tier="B",
                reason=intro_fail_reason,
            )
            return
        if outcome is None:
            return
        await _emit_gateway_span(
            trace,
            kind="gateway.executor.b_completed",
            session_id=session_id,
            turn_id=correlation_id,
            status=str(outcome.status),
            attrs={"final_count": len(outcome.final_messages)},
        )
        # Stash last-turn summary for regen continuity (transcript-review item #9).
        summary_tier = (
            triage.complexity.value
            if hasattr(triage.complexity, "value")
            else str(triage.complexity)
        )
        if outcome.status == "escalated" and outcome.escalation is not None:
            summary_tier = str(outcome.escalation.target_tier or summary_tier)
        router._last_turn_summary[session_id] = {
            "intent": (
                triage.intent.value if hasattr(triage.intent, "value") else str(triage.intent)
            ),
            "tier": summary_tier,
            "status": str(outcome.status),
            "correlation_id": correlation_id,
            "suggested_tier": summary_tier if outcome.status == "escalated" else None,
        }
        if bootstrap_active and await _bootstrap_capture_after_turn(
            bootstrap_active=True,
            content_root=layout.content_root,
            user_text=user_text,
            agent_name=agent_name,
            conn=conn,
            session_id=session_id,
        ):
            intro_outbound_marked = True
        final_texts = [
            text
            for payload in outcome.final_messages
            if (text := _deliverable_assistant_text(payload.text))
        ]
        if not final_texts and (outcome.status not in ("escalated",)):
            # Degrade gracefully: surface any partial progress the executor gathered
            # before it failed to compose a final answer (e.g. a tool looped to its
            # retry cap) instead of sending a bare "nothing to send".
            empty_reason = f"empty_output:status={outcome.status}"
            partial = _collect_partial_progress(finalizer=finalizer, outcome=outcome)
            if finalizer is not None:
                await finalizer.finalize(
                    status="empty",
                    text=_render_no_answer_message(empty_reason, partial_progress=partial),
                )
                return
            await _emit_no_answer_fallback(
                router=router,
                channel=sess.channel,
                user_id=sess.user_id,
                session_id=session_id,
                route_meta=route_meta,
                trace=trace,
                correlation_id=correlation_id,
                tier="B",
                reason=empty_reason,
                partial_progress=partial,
            )
            return
        if finalizer is not None and outcome.status != "escalated":
            # Concatenate multi-message outputs with a blank-line separator so the
            # finalizer still consumes the executor's output as a single message.
            joined = "\n\n".join(final_texts)
            joined = _strip_preamble_echo(joined, triage.first_message or "")
            joined, block_reason = _apply_tier_b_grounding_guard(
                joined,
                outcome,
                bound_tools=frozenset(triage.tools),
                steer_buffer=steer_buffer,
            )
            if block_reason:
                if finalizer is not None:
                    await finalizer.finalize(
                        status="empty",
                        text=_render_no_answer_message(block_reason),
                    )
                    return
                await _emit_no_answer_fallback(
                    router=router,
                    channel=sess.channel,
                    user_id=sess.user_id,
                    session_id=session_id,
                    route_meta=route_meta,
                    trace=trace,
                    correlation_id=correlation_id,
                    tier="B",
                    reason=block_reason,
                )
                return
            outbound_text, _applied = _apply_routing_footer_once(
                joined,
                triage=triage,
                triager_ms=triager_ms,
                enabled=show_routing,
                sent=routing_footer_sent,
            )
            if finalizer is not None:
                finalizer.metadata = _merge_provider_turn_metadata(finalizer.metadata, outcome)
            await finalizer.finalize(status="success", text=outbound_text)
            if not intro_outbound_marked:
                marked = await asyncio.to_thread(
                    maybe_mark_intro_done_if_bootstrap_complete,
                    conn,
                    session_id,
                    content_root=layout.content_root,
                    agent_name=agent_name,
                )
                if marked:
                    intro_outbound_marked = True
            return
        for i, text in enumerate(final_texts):
            phase = _outbound_phase_for_assistant_chunk(
                had_triager_first=had_triager_first,
                index=i,
                total=len(final_texts),
            )
            if i == 0:
                text = _strip_preamble_echo(text, triage.first_message or "")
                text, block_reason = _apply_tier_b_grounding_guard(
                    text,
                    outcome,
                    bound_tools=frozenset(triage.tools),
                    steer_buffer=steer_buffer,
                )
                if block_reason:
                    await _emit_no_answer_fallback(
                        router=router,
                        channel=sess.channel,
                        user_id=sess.user_id,
                        session_id=session_id,
                        route_meta=route_meta,
                        trace=trace,
                        correlation_id=correlation_id,
                        tier="B",
                        reason=block_reason,
                    )
                    return
            outbound_text, applied = _apply_routing_footer_once(
                text,
                triage=triage,
                triager_ms=triager_ms,
                enabled=show_routing,
                sent=routing_footer_sent,
            )
            routing_footer_sent = routing_footer_sent or applied
            chunk_meta = route_meta if i > 0 else _merge_provider_turn_metadata(route_meta, outcome)
            await _route_assistant_text(
                router,
                sess.channel,
                sess.user_id,
                session_id,
                outbound_text,
                metadata=chunk_meta,
                outbound_phase=phase,
            )
            if not intro_outbound_marked:
                marked = await asyncio.to_thread(
                    maybe_mark_intro_done_if_bootstrap_complete,
                    conn,
                    session_id,
                    content_root=layout.content_root,
                    agent_name=agent_name,
                )
                if marked:
                    intro_outbound_marked = True
        if outcome.status != "escalated" or outcome.escalation is None:
            return
        # Tier B is handing off to C/D. Keep the finalizer alive (Step 7a — the
        # same placeholder gets edited by C/D's terminal state) and just update its
        # text in-flight so the user sees something during the handoff window.
        if finalizer is not None and not finalizer.is_finalized:
            await finalizer.stream_update(
                "Escalating to tier C — this is taking longer than expected.",
            )
        esc = outcome.escalation
        cd_triage = triage
        if not triage_passthrough:
            cd_triage = await _retriage_after_escalation(
                workspace=workspace,
                session_view=session_view,
                incoming=incoming,
                user_text=user_text,
                escalation=esc,
                registry=registry,
                triage_ctx=triage_ctx,
                content_root=layout.content_root,
                trace=trace,
                turn_span_id=turn_span_id,
            )
        else:
            cd_triage = _synthetic_escalation_triage(esc)
        if cd_triage.complexity not in (ComplexityTier.C, ComplexityTier.D):
            requested_tier = str(esc.target_tier or "C")
            logger.info(
                "agent_turn.escalation_unavailable session_id={} complexity={} requested_tier={}",
                session_id,
                cd_triage.complexity,
                requested_tier,
            )
            await _emit_gateway_span(
                trace,
                kind="gateway.executor.escalation_unavailable",
                session_id=session_id,
                turn_id=correlation_id,
                status="unavailable",
                attrs={
                    "escalation_reason": esc.reason,
                    "requested_tier": requested_tier,
                    "cd_complexity": str(cd_triage.complexity),
                },
            )
            await _route_assistant_text(
                router,
                sess.channel,
                sess.user_id,
                session_id,
                ESCALATION_UNAVAILABLE_USER_MESSAGE,
                metadata=route_meta,
            )
            return
        await _run_cd_dispatch(
            router=router,
            conn=conn,
            workspace=workspace,
            layout=layout,
            trace=trace,
            session_id=session_id,
            correlation_id=correlation_id,
            turn_span_id=turn_span_id,
            sess_channel=sess.channel,
            sess_user_id=sess.user_id,
            triage=cd_triage,
            user_text=user_text,
            route_meta=route_meta,
            process=process,
            bindings=bindings,
            mcp_tool_definitions=mcp_defs,
            plan_registry=plan_registry,
            had_triager_first=had_triager_first,
            finalizer=finalizer,
            timeout_s=budget.clamp(tier_cd_timeout_s),
        )

    async def _run_guarded(session_id: str, correlation_id: str) -> None:
        """Outer catch-all wrapping ``_run`` so unexpected failures still notify the user."""
        terminal_status = "ok"
        turn_wall_ns = time_ns()
        try:
            await _run(session_id, correlation_id)
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            # P9: when cancel-mode already queued a replacement turn, skip the
            # "interrupted" terminal — the user sees the new opener/answer instead.
            depth, _running = router._sessions.dispatch_queue_snapshot(session_id)
            suppress_interrupt = depth > 0 or router._sessions.was_cancel_superseded_recently(
                session_id,
                within_s=_CANCEL_INTERRUPT_SUPPRESS_S,
            )
            if suppress_interrupt:
                logger.info(
                    "agent_turn.cancel_interrupt_suppressed session_id={} correlation_id={} "
                    "queue_depth={}",
                    session_id,
                    correlation_id,
                    depth,
                )
            else:
                # W4.2: guarantee the user always sees a terminal message even when their
                # in-flight tier-C turn is superseded by a new inbound message.  Shield the
                # cleanup calls so further cancellation signals do not silently swallow them.
                try:
                    _sess = await asyncio.shield(
                        asyncio.to_thread(load_session_row, conn, session_id)
                    )
                    if _sess is not None:
                        _route_meta = await asyncio.shield(
                            asyncio.to_thread(
                                _outbound_routing_metadata,
                                conn,
                                session_id,
                                _sess.channel,
                                _sess.user_id,
                            )
                        )
                        # W4.3: _emit_no_answer_fallback emits gateway.executor.no_answer span.
                        await asyncio.shield(
                            _emit_no_answer_fallback(
                                router=router,
                                channel=_sess.channel,
                                user_id=_sess.user_id,
                                session_id=session_id,
                                route_meta=_route_meta,
                                trace=trace,
                                correlation_id=correlation_id,
                                tier="?",
                                reason="cancelled_by_new_message",
                            )
                        )
                except Exception:
                    logger.exception(
                        "agent_turn_cancel_terminal_message_failed session_id={}",
                        session_id,
                    )
            raise
        except Exception:
            terminal_status = "error"
            logger.exception(
                "agent_turn_unhandled_error session_id={} correlation_id={}",
                session_id,
                correlation_id,
            )
            try:
                sess = await asyncio.to_thread(load_session_row, conn, session_id)
            except Exception:
                logger.exception(
                    "agent_turn_fallback_session_lookup_failed session_id={}",
                    session_id,
                )
                return
            if sess is None:
                return
            route_meta = await asyncio.to_thread(
                _outbound_routing_metadata,
                conn,
                session_id,
                sess.channel,
                sess.user_id,
            )
            await _emit_no_answer_fallback(
                router=router,
                channel=sess.channel,
                user_id=sess.user_id,
                session_id=session_id,
                route_meta=route_meta,
                trace=trace,
                correlation_id=correlation_id,
                tier="?",
                reason="unhandled_exception",
            )
        finally:
            await run_post_turn_hooks(
                PostTurnContext(
                    router=router,
                    conn=conn,
                    trace=trace,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    terminal_status=terminal_status,
                    turn_wall_ns=turn_wall_ns,
                )
            )

    return _run_guarded


async def _run_full_index_retry(
    *,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    bundle: ResolvedTierBModel,
    tool_set: Any,
    exe: Any,
    bindings: RuntimeToolBindings,
    router: ChannelRouter,
    trace: TraceSink,
    steer_buffer: SteerInject | None,
    channel_adapter: Any,
    turn_span_id: str,
    session_id: str,
    correlation_id: str,
    sess_channel: str,
    sess_user_id: str,
    route_meta: dict[str, Any],
    triage: Any,
    user_text: str,
    extra_instructions: str,
    streaming_sink: Any,
    finalizer: TierBAnswerFinalizer | None,
    first_attempt_reason: str,
    budget: CascadeBudget,
    transcript_turns: list[str] | None = None,
    transcript_rows: list[Any] | None = None,
    operator_local_date: str = "",
) -> tuple[Any | None, str | None]:
    """Run one tier-B retry with the full skills/INDEX exposed (`PROBLEMS.md` 1(e)).

    Edits the placeholder with the "Widening toolkit…" notice, then re-dispatches
    ``run_b_turn`` with ``full_index=True`` and the expanded round budget.

    Args:
        workspace (WorkspaceConfig): Parsed workspace for budget / model lookup.
        layout (WorkspaceLayout): Filesystem layout for repo + content root.
        bundle (ResolvedTierBModel): Resolved tier-B transport + budget.
        tool_set (Any): Active ``ToolSet`` from the session registry.
        exe (Any): Active ``ToolExecutor``.
        bindings (RuntimeToolBindings): Runtime tool bindings (integration, etc.).
        router (ChannelRouter): Gateway router for assistant dispatch.
        trace (TraceSink): Trace sink for the retry span.
        steer_buffer (SteerInject | None): Steer-channel buffer for the turn.
        channel_adapter (Any): Resolved adapter for the session's channel.
        turn_span_id (str): Turn root span id for parent linkage.
        session_id (str): Session identifier.
        correlation_id (str): Per-turn correlation id (also acts as turn_id).
        sess_channel (str): Session channel key (``telegram``, ``webchat``).
        sess_user_id (str): Session user id (channel-specific).
        route_meta (dict[str, Any]): Outbound routing metadata.
        triage (Any): Original triage row; harness ``model_copy``'s it with
            ``tools=<all>`` while preserving ``triage.skills`` when ``full_index=True``.
        user_text (str): Latest user message text.
        extra_instructions (str): Tier-B instruction extras (orientation, repo
            directive, intro/bootstrap, persona block).
        streaming_sink (Any): Optional ``StreamingSink`` forwarded into the
            harness; ``None`` for non-streaming modes.
        finalizer (TierBAnswerFinalizer | None): When non-``None``, the retry
            stream updates land on the same placeholder.
        first_attempt_reason (str): Machine label from the first failure (used
            for tracing only).
        transcript_turns (list[str] | None): Recent session transcript lines for
            tier-B context; mirrors the triager's transcript window.
        transcript_rows (list[Any] | None): Structured transcript rows for faithful
            cross-turn replay when ``replay_provider_history`` is set.
        budget (CascadeBudget): Cumulative cascade wall-clock budget for the turn.
        operator_local_date (str): Operator-local calendar date ``YYYY-MM-DD`` for
            live-factual tier-B prompts.

    Returns:
        tuple[BTurnOutcome | None, str | None]: ``(outcome, None)`` on success
        (caller flows into the regular outcome processing path), or
        ``(None, retry_reason)`` when the retry also fails — caller escalates
        to tier C/D.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_full_index_retry)
        True
    """
    _ = first_attempt_reason  # carried by trace, not consumed here
    if finalizer is not None and not finalizer.is_finalized:
        await finalizer.stream_update(
            "Widening toolkit and retrying — a tool error or timeout blocked the first pass.",
        )
    if budget.exhausted():
        return None, "cascade_budget_exhausted"
    expanded_rounds = tier_b_rounds_expanded(workspace)
    try:
        outcome = await asyncio.wait_for(
            run_b_turn(
                workspace=workspace,
                session=SessionHandle(session_id=session_id),
                turn_id=correlation_id,
                triage=triage,
                incoming_text=user_text,
                tool_set=tool_set,
                body_cache=LoadedBodyCache(capacity=8),
                tool_executor=exe,
                transport_bundle=bundle,
                trace=trace,
                steer_buffer=steer_buffer,
                operator_local_date=operator_local_date,
                extra_instructions=extra_instructions,
                tool_context=_tool_context_for_turn(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    workspace=workspace,
                    layout=layout,
                    trace=trace,
                    tool_set=tool_set,
                    channel=sess_channel,
                    channel_adapter=channel_adapter,
                    channel_router=router,
                    outbound_user_id=sess_user_id,
                    outbound_metadata=route_meta,
                    runtime_bindings=bindings,
                    plugin_hooks=_plugin_hooks_from_router(router),
                    turn_span_id=turn_span_id,
                ),
                max_rounds=expanded_rounds,
                streaming_sink=streaming_sink,
                full_index=True,
                transcript_turns=transcript_turns,
                transcript_rows=transcript_rows,
                return_partial_on_cancel=True,
            ),
            timeout=budget.clamp(tier_b_executor_timeout_s(workspace)),
        )
    except TimeoutError:
        return None, "timeout_full_index_retry"
    except Exception:
        logger.exception(
            "tier_b_full_index_retry_raised session_id={} correlation_id={}",
            session_id,
            correlation_id,
        )
        return None, "exception_full_index_retry"
    if outcome is None:
        return None, "missing_outcome_full_index_retry"
    # Treat empty + non-escalated outcome as a retry failure too.
    final_texts = [
        (payload.text or "").strip()
        for payload in outcome.final_messages
        if (payload.text or "").strip()
    ]
    if not final_texts and outcome.status != "escalated":
        return None, f"empty_output_full_index_retry:status={outcome.status}"
    return outcome, None


async def _run_b_fallback_for_cd(
    *,
    router: ChannelRouter,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    trace: TraceSink,
    session_id: str,
    correlation_id: str,
    turn_span_id: str,
    sess_channel: str,
    sess_user_id: str,
    triage: Any,
    user_text: str,
    route_meta: dict[str, Any],
    process: ProcessSettings,
    bindings: RuntimeToolBindings,
    exe: Any,
    tool_set: Any,
    channel_adapter: Any,
    steer_buffer: Any,
    had_triager_first: bool,
    finalizer: TierBAnswerFinalizer | None,
    timeout_s: float | None,
    operator_local_date: str = "",
) -> bool:
    """Answer a decompose-failed C/D turn with a plain tier-B pass on the same text.

    A deterministic decompose parse/schema fault is non-recoverable for the C/D
    contract but says nothing about the request itself — a direct tier-B answer is
    almost always the right degradation (`prd/04-getting-things-done.md`;
    `specs/21-executor-tier-cd.md`). Runs ``run_b_turn`` with a B-clamped triage copy
    and delivers the result into the same placeholder (finalizer) or as a fresh send.

    Args:
        router (ChannelRouter): Gateway router.
        workspace (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Filesystem layout.
        trace (TraceSink): Trace sink.
        session_id (str): Owning session id.
        correlation_id (str): Turn correlation id.
        turn_span_id (str): Turn root span id.
        sess_channel (str): Session channel key.
        sess_user_id (str): Session user id.
        triage (TriageResult): Original C/D triage row (cloned to B here).
        user_text (str): Latest user message text.
        route_meta (dict[str, Any]): Outbound routing metadata.
        process (ProcessSettings): Process settings for transport resolution.
        bindings (RuntimeToolBindings): Tool runtime bindings.
        exe (Any): Active ``ToolExecutor`` from the C/D session registry.
        tool_set (Any): Active ``ToolSet`` from the C/D session registry.
        channel_adapter (Any): Resolved adapter for the session channel.
        steer_buffer (Any): Steer-channel buffer for the turn.
        had_triager_first (bool): Triager ``first_message`` already delivered.
        finalizer (TierBAnswerFinalizer | None): When non-``None``, deliver into it.
        timeout_s (float | None): Wall-clock cap; falls back to the tier-B timeout.
        operator_local_date (str): Operator-local calendar date ``YYYY-MM-DD`` for
            live-factual tier-B prompts.

    Returns:
        bool: ``True`` when a non-empty tier-B answer was delivered; ``False`` when
        the fallback produced nothing (caller emits a generic no-answer message).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_b_fallback_for_cd)
        True
    """
    b_triage = triage.model_copy(update={"complexity": ComplexityTier.B})
    bundle = _resolve_tier_b_bundle(workspace, process)
    bootstrap = await asyncio.to_thread(load_bootstrap_markdown_cached, layout.content_root)
    _ = bootstrap  # parity with the main path; intro/bootstrap not re-injected here
    extra_parts: list[str] = []
    orient = orientation_block_for_workspace(
        workspace,
        content_root=layout.content_root,
        intent=infer_orientation_intent(user_text),
    )
    if orient.strip():
        extra_parts.append(orient)
    if is_repo_code_intent_message(user_text):
        extra_parts.append(tier_b_self_architecture_inject())
    if is_routing_footer_query(user_text):
        extra_parts.append(tier_b_routing_footer_inject())
    extra_parts.append(tier_b_repo_access_prompt(workspace, layout.content_root))
    extra_instructions = "\n\n".join(p for p in extra_parts if p.strip())
    streaming_sink = (
        finalizer.stream_update
        if finalizer is not None and tier_b_answer_mode(workspace) == "stream"
        else None
    )
    try:
        outcome = await asyncio.wait_for(
            run_b_turn(
                workspace=workspace,
                session=SessionHandle(session_id=session_id),
                turn_id=correlation_id,
                triage=b_triage,
                incoming_text=user_text,
                tool_set=tool_set,
                body_cache=LoadedBodyCache(capacity=8),
                tool_executor=exe,
                transport_bundle=bundle,
                trace=trace,
                steer_buffer=steer_buffer,
                operator_local_date=operator_local_date,
                extra_instructions=extra_instructions,
                tool_context=_tool_context_for_turn(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    workspace=workspace,
                    layout=layout,
                    trace=trace,
                    tool_set=tool_set,
                    channel=sess_channel,
                    channel_adapter=channel_adapter,
                    channel_router=router,
                    outbound_user_id=sess_user_id,
                    outbound_metadata=route_meta,
                    runtime_bindings=bindings,
                    plugin_hooks=_plugin_hooks_from_router(router),
                    turn_span_id=turn_span_id,
                ),
                streaming_sink=streaming_sink,
                return_partial_on_cancel=True,
            ),
            timeout=timeout_s if timeout_s is not None else tier_b_executor_timeout_s(workspace),
        )
    except TimeoutError:
        return False
    except Exception:
        logger.exception(
            "cd_decompose_b_fallback_raised session_id={} correlation_id={}",
            session_id,
            correlation_id,
        )
        return False
    if outcome is None:
        return False
    b_texts = [
        text
        for payload in outcome.final_messages
        if (text := _deliverable_assistant_text(payload.text))
    ]
    if not b_texts:
        return False
    if finalizer is not None and not finalizer.is_finalized:
        joined = "\n\n".join(b_texts)
        joined = _strip_preamble_echo(joined, getattr(triage, "first_message", "") or "")
        joined, _block_reason = _apply_tier_b_grounding_guard(
            joined,
            outcome,
            bound_tools=frozenset(getattr(triage, "tools", ()) or ()),
            steer_buffer=steer_buffer,
        )
        if not joined.strip():
            return False
        await finalizer.finalize(status="success", text=joined)
        return True
    for i, text in enumerate(b_texts):
        phase = _outbound_phase_for_assistant_chunk(
            had_triager_first=had_triager_first,
            index=i,
            total=len(b_texts),
        )
        await _route_assistant_text(
            router,
            sess_channel,
            sess_user_id,
            session_id,
            text,
            metadata=route_meta,
            outbound_phase=phase,
        )
    return True


async def _run_cd_dispatch(
    *,
    router: ChannelRouter,
    conn: sqlite3.Connection,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    trace: TraceSink,
    session_id: str,
    correlation_id: str,
    turn_span_id: str,
    sess_channel: str,
    sess_user_id: str,
    triage: Any,
    user_text: str,
    route_meta: dict[str, Any],
    process: ProcessSettings,
    bindings: RuntimeToolBindings,
    mcp_tool_definitions: tuple[ToolDefinition, ...] = (),
    plan_registry: PlanGateWaitRegistry,
    had_triager_first: bool = False,
    finalizer: TierBAnswerFinalizer | None = None,
    timeout_s: float | None = None,
) -> None:
    """Execute ``run_cd_turn`` and map ``CdTurnOutcome`` payloads outbound.

    Args:
        router (ChannelRouter): Gateway router.
        conn (sqlite3.Connection): SQLite handle.
        workspace (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Filesystem layout.
        trace (TraceSink): Trace sink.
        session_id (str): Owning session id.
        correlation_id (str): Turn correlation id.
        turn_span_id (str): Turn root span id for parent linkage.
        sess_channel (str): Session channel key.
        sess_user_id (str): Session user id.
        triage (TriageResult): Triager row with complexity C or D.
        user_text (str): Latest user message text.
        route_meta (dict[str, Any]): Outbound routing metadata.
        process (ProcessSettings): Process settings for transport resolution.
        bindings (RuntimeToolBindings): Tool runtime bindings.
        mcp_tool_definitions (tuple[ToolDefinition, ...]): MCP tool descriptors forwarded
            to ``build_session_registry`` as ``extra_mcp``.
        plan_registry (PlanGateWaitRegistry): Shared PlanGate waiters.
        had_triager_first (bool): Triager ``first_message`` already sent as ``persist``.
        finalizer (TierBAnswerFinalizer | None): When non-``None``, the C/D outcome
            edits this placeholder via ``finalize(...)`` instead of being routed as
            fresh assistant sends. Wired so the cascade keeps the same placeholder
            bubble (`PROBLEMS.md` Priority 1(e), Step 7a).
        timeout_s (float | None): Wall-clock cap for ``run_cd_turn``. ``None``
            falls back to ``TIER_CD_EXECUTOR_TIMEOUT_S``; callers typically pass
            ``CascadeBudget.clamp(TIER_CD_EXECUTOR_TIMEOUT_S)`` so the
            180s cumulative cascade budget is enforced (Step 7b).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_run_cd_dispatch)
        True
    """
    bundle = _resolve_cd_outer_models(workspace, process, triage.complexity)
    exe, tool_set = await asyncio.to_thread(
        build_session_registry,
        workspace_config=workspace,
        runtime_bindings=bindings,
        extra_mcp=mcp_tool_definitions,
        workspace_root=layout.content_root,
        layout=layout,
        trace_sink=trace,
    )
    channel_adapter = router.adapter_named(sess_channel)
    plan_gate = _plan_gate_for_turn(
        conn=conn,
        router=router,
        registry=plan_registry,
        workspace=workspace,
        channel=sess_channel,
        user_id=sess_user_id,
        route_meta=route_meta,
    )
    steer_buffer = _steer_buffer_for(router, session_id)
    cd_outcome = None
    cd_no_answer_reason: str | None = None
    cd_tier_label = "C" if str(triage.complexity).endswith("C") else "D"
    try:
        cd_outcome = await asyncio.wait_for(
            run_cd_turn(
                workspace=workspace,
                session=SessionHandle(session_id=session_id),
                turn_id=correlation_id,
                triage=triage,
                incoming_text=user_text,
                tool_set=tool_set,
                body_cache=LoadedBodyCache(capacity=8),
                transport_outer=bundle,
                trace=trace,
                steer_buffer=steer_buffer,
                plan_gate=plan_gate,
                tool_executor=exe,
                tool_context=_tool_context_for_turn(
                    session_id=session_id,
                    correlation_id=correlation_id,
                    workspace=workspace,
                    layout=layout,
                    trace=trace,
                    tool_set=tool_set,
                    channel=sess_channel,
                    channel_adapter=channel_adapter,
                    channel_router=router,
                    outbound_user_id=sess_user_id,
                    outbound_metadata=route_meta,
                    runtime_bindings=bindings,
                    plugin_hooks=_plugin_hooks_from_router(router),
                    turn_span_id=turn_span_id,
                ),
            ),
            timeout=timeout_s if timeout_s is not None else tier_cd_executor_timeout_s(workspace),
        )
    except TimeoutError:
        cd_no_answer_reason = "timeout"
    except Exception:
        logger.exception(
            "tier_cd_executor_raised session_id={} correlation_id={}",
            session_id,
            correlation_id,
        )
        cd_no_answer_reason = "exception"
    if cd_no_answer_reason is not None or cd_outcome is None:
        if finalizer is not None and not finalizer.is_finalized:
            status_label: Any = "timeout" if cd_no_answer_reason == "timeout" else "error"
            await finalizer.finalize(
                status=status_label,
                text=_render_no_answer_message(cd_no_answer_reason or "missing_outcome"),
            )
            return
        await _emit_no_answer_fallback(
            router=router,
            channel=sess_channel,
            user_id=sess_user_id,
            session_id=session_id,
            route_meta=route_meta,
            trace=trace,
            correlation_id=correlation_id,
            tier=cd_tier_label,
            reason=cd_no_answer_reason or "missing_outcome",
        )
        return
    await _emit_gateway_span(
        trace,
        kind="gateway.executor.cd_completed",
        session_id=session_id,
        turn_id=correlation_id,
        status=str(cd_outcome.status),
        attrs={
            "final_count": len(cd_outcome.final_messages),
            "c_d_backend": cd_outcome.c_d_backend,
        },
    )
    # A deterministic decompose parse/schema failure must never surface the raw
    # planner error to the user (`prd/04-getting-things-done.md`). Degrade to a plain
    # tier-B answer for the same message instead.
    if cd_outcome.status == "failed" and _is_deterministic_harness_failure(
        no_answer_reason=None, outcome=cd_outcome
    ):
        await _emit_gateway_span(
            trace,
            kind="gateway.executor.cd_decompose_b_fallback",
            session_id=session_id,
            turn_id=correlation_id,
            status="started",
            attrs={"failure_detail": str(getattr(cd_outcome, "failure_detail", ""))},
        )
        if await _run_b_fallback_for_cd(
            router=router,
            workspace=workspace,
            layout=layout,
            trace=trace,
            session_id=session_id,
            correlation_id=correlation_id,
            turn_span_id=turn_span_id,
            sess_channel=sess_channel,
            sess_user_id=sess_user_id,
            triage=triage,
            user_text=user_text,
            route_meta=route_meta,
            process=process,
            bindings=bindings,
            exe=exe,
            tool_set=tool_set,
            channel_adapter=channel_adapter,
            steer_buffer=steer_buffer,
            had_triager_first=had_triager_first,
            finalizer=finalizer,
            timeout_s=timeout_s,
        ):
            return
        # B fallback produced nothing usable — fall through to the normal outcome
        # path, which emits a no-answer fallback (never the raw parser snippet).
        cd_outcome = dataclasses.replace(cd_outcome, final_messages=())
    cd_texts = [
        text
        for payload in cd_outcome.final_messages
        if (text := _deliverable_assistant_text(payload.text))
    ]
    if not cd_texts:
        if finalizer is not None and not finalizer.is_finalized:
            await finalizer.finalize(
                status="empty",
                text=_render_no_answer_message(f"empty_output:status={cd_outcome.status}"),
            )
            return
        await _emit_no_answer_fallback(
            router=router,
            channel=sess_channel,
            user_id=sess_user_id,
            session_id=session_id,
            route_meta=route_meta,
            trace=trace,
            correlation_id=correlation_id,
            tier=cd_tier_label,
            reason=f"empty_output:status={cd_outcome.status}",
        )
        return
    if finalizer is not None and not finalizer.is_finalized:
        # Cascade success: deliver the C/D answer into the same placeholder so the
        # user sees one bubble update (`PROBLEMS.md` Priority 1(e) — "Cascade edits
        # the same placeholder").
        joined = "\n\n".join(cd_texts)
        joined = _strip_preamble_echo(joined, getattr(triage, "first_message", "") or "")
        await finalizer.finalize(status="success", text=joined)
        return
    for i, text in enumerate(cd_texts):
        phase = _outbound_phase_for_assistant_chunk(
            had_triager_first=had_triager_first,
            index=i,
            total=len(cd_texts),
        )
        await _route_assistant_text(
            router,
            sess_channel,
            sess_user_id,
            session_id,
            text,
            metadata=route_meta,
            outbound_phase=phase,
        )


def _plan_gate_for_turn(
    *,
    conn: sqlite3.Connection,
    router: ChannelRouter,
    registry: PlanGateWaitRegistry,
    workspace: WorkspaceConfig,
    channel: str,
    user_id: str,
    route_meta: dict[str, Any],
) -> Any:
    """Select PlanGate implementation from workspace ``plan_approval.enabled``.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        router (ChannelRouter): Gateway router for plan post.
        registry (PlanGateWaitRegistry): In-process waiters.
        workspace (WorkspaceConfig): Parsed workspace.
        channel (str): Delivery channel key.
        user_id (str): Session owner user id.
        route_meta (dict[str, Any]): Outbound routing metadata.

    Returns:
        Any: ``PlanGatePort`` implementation.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> g = _plan_gate_for_turn(
        ...     conn=__import__("sqlite3").connect(":memory:"),
        ...     router=object(),
        ...     registry=PlanGateWaitRegistry(),
        ...     workspace=WorkspaceConfig.minimal(),
        ...     channel="telegram",
        ...     user_id="1",
        ...     route_meta={},
        ... )
        >>> isinstance(g, NoOpPlanGate)
        True
    """
    enabled = False
    section = workspace.plan_approval
    if section is not None:
        enabled = bool(section.enabled)
    if enabled and channel == "telegram":
        return SqlitePlanGate(
            conn=conn,
            router=router,
            registry=registry,
            channel=channel,
            user_id=user_id,
            route_metadata=route_meta,
        )
    if enabled:
        return ImmediateApprovedPlanGate()
    return NoOpPlanGate()


def _resolve_cd_outer_models(
    workspace: WorkspaceConfig,
    process: ProcessSettings,
    complexity: ComplexityTier,
) -> ResolvedCdOuterModels:
    """Resolve tier C/D outer + sub-LM transports for ``run_cd_turn``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        process (ProcessSettings): Process settings (proxy URL).
        complexity (ComplexityTier): Triager complexity **C** or **D**.

    Returns:
        ResolvedCdOuterModels: Bundle for the C/D harness.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolve_cd_outer_models)
        True
    """
    outer_slot = ModelSlot.tier_c if complexity == ComplexityTier.C else ModelSlot.tier_d
    sub_slot = ModelSlot.c_sub_lm if complexity == ComplexityTier.C else ModelSlot.d_sub_lm
    providers = _providers_mapping(workspace)
    outer_id = resolve_model_slot(workspace, outer_slot)
    outer_transport_name = resolve_transport_for_model_id(providers, outer_id)
    _, outer_transport = resolve_model(
        model_id=outer_id,
        transport_name=outer_transport_name,
        proxy_base_url=process.proxy_url,
    )
    outer_budget = ModelBudget(model_id=outer_id, regime=BudgetRegime.PER_TOKEN)
    sub_id = resolve_model_slot(workspace, sub_slot)
    sub_transport_name = resolve_transport_for_model_id(providers, sub_id)
    _, sub_transport = resolve_model(
        model_id=sub_id,
        transport_name=sub_transport_name,
        proxy_base_url=process.proxy_url,
    )
    sub_budget = ModelBudget(model_id=sub_id, regime=BudgetRegime.PER_TOKEN)
    return ResolvedCdOuterModels(
        outer_model_id=outer_id,
        outer_transport=outer_transport,
        outer_budget=outer_budget,
        sub_lm_model_id=sub_id,
        sub_lm_transport=sub_transport,
        sub_lm_budget=sub_budget,
    )


async def _retriage_after_escalation(
    *,
    workspace: WorkspaceConfig,
    session_view: Any,
    incoming: ApprovedUserTurn,
    user_text: str,
    escalation: EscalationRequest,
    registry: Any,
    triage_ctx: Any,
    content_root: Path,
    trace: TraceSink,
    turn_span_id: str,
) -> Any:
    """Re-run Triager after tier-B escalation (``specs/17-gateway.md`` §2.6 step 9).

    Args:
        workspace (WorkspaceConfig): Parsed workspace.
        session_view (SessionView): Gateway session view for Triager.
        incoming (ApprovedUserTurn): Original approved user turn.
        user_text (str): Latest user plaintext.
        escalation (EscalationRequest): Structured B → C/D handoff.
        registry (RegistrySnapshot): Tool registry snapshot.
        triage_ctx (TriagePromptContext): Base triage suffix context.
        content_root (Path): Workspace content root for persona ``system_prompt``.
        trace (TraceSink): Gateway trace sink for second-pass ``triage.*`` spans.
        turn_span_id (str): Turn root span id for parent linkage.

    Returns:
        TriageResult: Second-pass routing row.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_retriage_after_escalation)
        True
    """
    augment = (
        f"{user_text}\n\n"
        f"[Escalation from tier B: {escalation.reason}; "
        f"suggested tier {escalation.target_tier}]"
    )
    ctx = triage_ctx.model_copy(update={"current_message": augment})
    result = await triage_turn(
        workspace=workspace,
        session=session_view,
        incoming=incoming,
        registry_snapshot=registry,
        triage_context=ctx,
        content_root=content_root,
        trace=trace,
        turn_span_id=turn_span_id,
    )
    # W4.1: union-merge the original tier-B tool list so the re-diagnosis never
    # silently drops the tool the user actually requested (e.g. ``serp``).
    if escalation.original_tools:
        merged = sorted(set(result.tools) | set(escalation.original_tools))
        result = result.model_copy(update={"tools": merged})
    return result


def _synthetic_escalation_triage(escalation: EscalationRequest) -> Any:
    """Build a tier C/D ``TriageResult`` when Triager is disabled.

    FL-4B.4 / L5: ``original_tools`` from the escalation request are threaded
    through to the synthetic triage so a pinned evolution bundle (or any other
    pre-built allowlist) is **not dropped** by the B→C path.  The ``tools``
    field is populated from ``escalation.original_tools`` rather than hard-coded
    to ``[]``.

    Args:
        escalation (EscalationRequest): Tier-B escalation hint.

    Returns:
        TriageResult: Synthetic row for ``run_cd_turn``.

    Examples:
        >>> from sevn.agent.executors.b_types import EscalationRequest
        >>> from sevn.agent.triager.models import ComplexityTier
        >>> r = _synthetic_escalation_triage(
        ...     EscalationRequest(
        ...         reason="r",
        ...         target_tier="C",
        ...         user_visible_message="m",
        ...     ),
        ... )
        >>> r.complexity == ComplexityTier.C
        True
        >>> r.tools
        []
        >>> r2 = _synthetic_escalation_triage(
        ...     EscalationRequest(
        ...         reason="r",
        ...         target_tier="C",
        ...         user_visible_message="m",
        ...         original_tools=("read", "edit", "integration_call"),
        ...     ),
        ... )
        >>> sorted(r2.tools)
        ['edit', 'integration_call', 'read']
    """
    tier = ComplexityTier.C if escalation.target_tier == "C" else ComplexityTier.D
    pinned_tools: list[str] = list(escalation.original_tools) if escalation.original_tools else []
    return TriageResult.model_construct(
        intent=Intent.UNKNOWN,
        complexity=tier,
        first_message="",
        tools=pinned_tools,
        skills=[],
        mcp_servers_required=[],
        permission_scope_narrowing=None,
        confidence=0.5,
        requires_vision=False,
        requires_document=False,
        disregard=False,
    )


def _steer_buffer_for(router: ChannelRouter, session_id: str) -> SteerInject | None:
    """Return the session-bound steer inject when the router wired a store.
    Args:
        router (ChannelRouter): Gateway router (may carry ``_steer_store``).
        session_id (str): Owning session id for this dispatch.
    Returns:
        SteerInject | None: Inject façade for tier B/C/D, or ``None`` when unset.
    Examples:
        >>> _steer_buffer_for(type("R", (), {"_steer_store": None})(), "s") is None
        True
    """
    store = getattr(router, "_steer_store", None)
    if store is None:
        return None
    return cast("SteerInject | None", store.steer_inject_for(session_id))


def _outbound_routing_metadata(
    conn: sqlite3.Connection,
    session_id: str,
    channel: str,
    user_id: str,
) -> dict[str, Any]:
    """Load adapter routing hints for replies (``chat_id``, topic, reply targets).
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        channel (str): Session channel key (e.g. ``telegram``).
        user_id (str): Session user id string.
    Returns:
        dict[str, Any]: Metadata for :class:`~sevn.gateway.channel_router.OutgoingMessage`.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_outbound_routing_metadata)
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
    if row is not None and row[0]:
        try:
            parsed = json.loads(str(row[0]))
            md = outbound_routing_metadata(parsed if isinstance(parsed, dict) else None)
            if isinstance(parsed, dict):
                voice_last = parsed.get("voice_user_text_last_turn")
                if isinstance(voice_last, str) and voice_last.strip():
                    md = dict(md)
                    md["voice_user_text_last_turn"] = voice_last.strip()
            if md.get("chat_id") is not None or md.get("voice_user_text_last_turn"):
                return md
        except json.JSONDecodeError:
            logger.warning(
                "agent_turn invalid user extras_json session_id={}",
                session_id,
            )
    if channel == "telegram" and user_id.isdigit():
        return {"chat_id": int(user_id)}
    return {}


def _latest_user_message_text(conn: sqlite3.Connection, session_id: str) -> str:
    """Return the newest user ``message`` row content for ``session_id``.
    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
    Returns:
        str: Latest user plaintext or empty string.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_latest_user_message_text)
        True
    """
    rows = latest_messages(conn, session_id)
    for row in reversed(rows):
        if row.get("role") == "user" and row.get("kind") == "message":
            return str(row.get("content") or "")
    return ""


def _pending_user_messages_text(conn: sqlite3.Connection, session_id: str) -> str:
    """Merge all unanswered user messages at the tail into one triage input.

    Under ``gateway.queue_mode = cancel`` a burst of quick successive messages
    is collapsed into a single surviving turn (the latest inbound supersedes the
    in-flight dispatch). The executor still sees every pending user line in its
    transcript context and answers them together, but triage only ever saw the
    *latest* message — so it selected a narrow toolset and the earlier questions
    were answered with the wrong tools (the "capability hallucination" of the
    MiniMax-M3 session: weather + list-folders answered with a who-are-you
    toolset). Merging the consecutive trailing user messages (those after the
    last assistant ``message`` row) gives triage the union of all asked
    questions so tool selection covers every one (`specs/17-gateway.md` §2.5).

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.

    Returns:
        str: Newline-joined pending user lines (newest last), or the latest user
        text when only one is pending. Empty string when none are pending.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_pending_user_messages_text)
        True
    """
    rows = latest_messages(conn, session_id)
    pending: list[str] = []
    for row in reversed(rows):
        if row.get("kind") != "message":
            continue
        role = row.get("role")
        if role == "assistant":
            break
        if role == "user":
            text = str(row.get("content") or "").strip()
            if text:
                pending.append(text)
    if not pending:
        return _latest_user_message_text(conn, session_id)
    # ``pending`` is newest-first from the reversed scan; restore chronological
    # order so the merged prompt reads top-to-bottom as the user typed it.
    pending.reverse()
    # Drop adjacent duplicates (e.g. an accidental double-send) without
    # resurrecting anything before the last assistant turn.
    deduped: list[str] = []
    for line in pending:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n\n".join(deduped)


def _is_retry_back_reference(text: str) -> bool:
    """Return whether ``text`` is a short "retry previous request" utterance.

    Args:
        text (str): Raw latest user message.

    Returns:
        bool: True when text is a retry/back-reference phrase.

    Examples:
        >>> _is_retry_back_reference("try again")
        True
        >>> _is_retry_back_reference("again?")
        True
        >>> _is_retry_back_reference("list source_code/src")
        False
    """
    return is_retry_back_reference_phrase(text)


def _looks_unfinished_assistant_reply(text: str) -> bool:
    """Return True when ``text`` matches a known no-answer/failure line.

    Args:
        text (str): Assistant message body.

    Returns:
        bool: True when the assistant line signals incomplete work.

    Examples:
        >>> _looks_unfinished_assistant_reply("I finished the turn but had nothing to send.")
        True
        >>> _looks_unfinished_assistant_reply("Here are the folders you asked for.")
        False
    """
    return looks_like_unfinished_assistant_reply(text)


def _resolve_retry_back_reference(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    latest_text: str,
) -> str | None:
    """Map a short retry phrase to the previous unfinished user request.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        latest_text (str): Current user message text.

    Returns:
        str | None: Prior user request to resume, else ``None``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolve_retry_back_reference)
        True
    """
    if not _is_retry_back_reference(latest_text):
        return None
    rows = conn.execute(
        """
        SELECT id, role, kind, content
        FROM gateway_messages
        WHERE session_id = ?
        ORDER BY id ASC
        """,
        (session_id,),
    ).fetchall()
    if not rows:
        return None
    anchor_index = -1
    needle = latest_text.strip()
    for idx, row in enumerate(rows):
        if (
            str(row[1]) == "user"
            and str(row[2]) == "message"
            and str(row[3] or "").strip() == needle
        ):
            anchor_index = idx
    if anchor_index <= 0:
        return None
    saw_unfinished_reply = False
    for idx in range(anchor_index - 1, -1, -1):
        role = str(rows[idx][1])
        kind = str(rows[idx][2])
        content = str(rows[idx][3] or "").strip()
        if kind != "message" or not content:
            continue
        if role == "assistant":
            if _looks_unfinished_assistant_reply(content):
                saw_unfinished_reply = True
                continue
            if saw_unfinished_reply:
                break
            continue
        if role == "user" and saw_unfinished_reply:
            if content.strip().lower() != needle.lower():
                return content
            break
    return None


def _providers_mapping(workspace: WorkspaceConfig) -> dict[str, Any]:
    """Normalize workspace ``providers`` to a plain dict for transport resolution.
    Args:
        workspace (WorkspaceConfig): Parsed workspace.
    Returns:
        dict[str, Any]: Providers block or empty dict.
    Examples:
        >>> _providers_mapping(WorkspaceConfig.minimal())
        {}
    """
    raw = workspace.providers
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    return {}


def _resolve_tier_b_bundle(
    workspace: WorkspaceConfig,
    process: ProcessSettings,
) -> ResolvedTierBModel:
    """Resolve tier-B model + transport for ``run_b_turn``.
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        process (ProcessSettings): Process settings (proxy URL).
    Returns:
        ResolvedTierBModel: Bundle passed to the tier-B harness.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_resolve_tier_b_bundle)
        True
    """
    model_id = resolve_model_slot(workspace, ModelSlot.tier_b)
    transport_name = resolve_transport_for_model_id(_providers_mapping(workspace), model_id)
    _, transport = resolve_model(
        model_id=model_id,
        transport_name=transport_name,
        proxy_base_url=process.proxy_url,
    )
    return ResolvedTierBModel(
        model_id=model_id,
        transport=transport,
        budget=ModelBudget(model_id=model_id, regime=BudgetRegime.PER_TOKEN),
    )


async def _bootstrap_capture_after_turn(
    *,
    bootstrap_active: bool,
    content_root: Path,
    user_text: str,
    agent_name: str,
    conn: sqlite3.Connection,
    session_id: str,
    write: bool = True,
) -> bool:
    """Run deterministic USER.md fallback and mark intro done when bootstrap completes.

    Args:
        bootstrap_active (bool): Whether bootstrap capture is open for this scope.
        content_root (Path): Workspace content root.
        user_text (str): Latest user message for heuristics.
        agent_name (str): Bot display name for completion checks.
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        write (bool): When ``False``, skip the heuristic USER.md write and only run
            the completion mark.  Pass ``False`` at the pre-triage callsite so that
            ``bootstrap_active`` / ``triage_ctx`` are refreshed without performing a
            speculative write before tier-B has a chance to capture structured answers.

    Returns:
        bool: True when ``intro_state`` was updated to ``done``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_bootstrap_capture_after_turn)
        True
    """
    if not bootstrap_active:
        return False
    if write:
        from sevn.gateway.bootstrap_capture import try_bootstrap_user_md_fallback

        await asyncio.to_thread(
            try_bootstrap_user_md_fallback,
            content_root,
            user_text,
            agent_name=agent_name,
        )
    return await asyncio.to_thread(
        maybe_mark_intro_done_if_bootstrap_complete,
        conn,
        session_id,
        content_root=content_root,
        agent_name=agent_name,
    )


def _permission_policy_from_workspace(
    workspace: WorkspaceConfig,
    *,
    channel: str = "",
    user_id: str = "",
) -> PermissionPolicy:
    """Resolve the session permission ceiling from ``permissions.default_profile``.

    Supported profile modes (``permissions.profiles.<key>.mode``):

    - ``deny_all`` — :class:`~sevn.tools.permissions.DenyingPermissionPolicy`.
    - ``abac`` — :class:`~sevn.tools.permissions.AttributeBasedPermissionPolicy`;
      principal is resolved from ``channel`` + ``user_id`` relative to the workspace
      owner allowlist (``channels.telegram.allowed_users``).  Loopback channels
      (``"local_open"``, ``"webchat"``) are always treated as the owner (D4).
    - ``deny_tools`` list — static deny-by-name policy.
    - (default) — :class:`~sevn.tools.permissions.AllowAllPermissionPolicy`.

    The default when no ``permissions`` block is configured is always
    :class:`~sevn.tools.permissions.AllowAllPermissionPolicy`, preserving today's
    behaviour for loopback / owner-DM Telegram and local-Web sessions (D4).

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        channel (str): Session channel key forwarded for ABAC principal resolution.
        user_id (str): Session user id forwarded for ABAC principal resolution.

    Returns:
        PermissionPolicy: Profile-backed deny list, deny-all, ABAC, or permissive default.

    Examples:
        >>> _permission_policy_from_workspace(WorkspaceConfig.minimal()).may_invoke("x")
        True
        >>> cfg = WorkspaceConfig.minimal(permissions={"default_profile": "p", "profiles": {"p": {"mode": "abac"}}})
        >>> _permission_policy_from_workspace(cfg, channel="local_open", user_id="").may_invoke("web_search")
        True
        >>> _permission_policy_from_workspace(cfg, channel="telegram", user_id="9").may_invoke("web_search")
        False
    """
    raw = workspace.permissions if isinstance(workspace.permissions, dict) else {}
    profile_key = raw.get("default_profile")
    profiles = raw.get("profiles")
    if isinstance(profile_key, str) and isinstance(profiles, dict):
        body = profiles.get(profile_key)
        if isinstance(body, dict):
            deny_raw = body.get("deny_tools")
            if isinstance(deny_raw, list):
                denied = frozenset(str(x).strip() for x in deny_raw if str(x).strip())

                class _DenyListed:
                    def may_invoke(self, tool_name: str) -> bool:
                        return tool_name not in denied

                return _DenyListed()
            mode = str(body.get("mode", "")).strip().lower()
            if mode == "deny_all":
                return DenyingPermissionPolicy()
            if mode == "abac":
                # Resolve the owner allowlist from the workspace Telegram config.
                owner_ids: frozenset[str] = frozenset()
                ch = workspace.channels
                if ch is not None and ch.telegram is not None:
                    allowed = ch.telegram.allowed_users or []
                    owner_ids = frozenset(str(int(uid)) for uid in allowed)
                principal = resolve_principal(
                    channel=channel,
                    user_id=user_id,
                    owner_user_ids=owner_ids,
                )
                return AttributeBasedPermissionPolicy(principal)
    return AllowAllPermissionPolicy()


def _tool_context_for_turn(
    *,
    session_id: str,
    correlation_id: str,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    trace: TraceSink,
    tool_set: Any,
    channel: str,
    channel_adapter: Any | None,
    channel_router: ChannelRouter,
    outbound_user_id: str,
    outbound_metadata: dict[str, Any],
    runtime_bindings: RuntimeToolBindings,
    plugin_hooks: Any | None,
    turn_span_id: str | None = None,
) -> ToolContext:
    """Build the tier-B ``ToolContext`` template for one gateway dispatch.
    Args:
        session_id (str): Owning session id.
        correlation_id (str): Turn / correlation id from the router queue.
        workspace (WorkspaceConfig): Parsed workspace configuration.
        layout (WorkspaceLayout): Resolved filesystem layout.
        trace (TraceSink): Gateway trace sink.
        tool_set (ToolSet): Immutable registry snapshot from ``build_session_registry``.
        channel (str): Active delivery channel key.
        channel_adapter (Any | None): Registered adapter for ``channel``.
        channel_router (ChannelRouter): Gateway router for proactive ``route_outgoing``.
        outbound_user_id (str): Session user id for outbound tool defaults.
        outbound_metadata (dict[str, Any]): Adapter routing hints for replies.
        runtime_bindings (RuntimeToolBindings): Sandbox/MCP/integration hooks when wired.
        plugin_hooks (Any | None): Optional :class:`~sevn.plugins.runner.PluginHookChain`.
        turn_span_id (str | None): Turn root span id for trace parent linkage.
    Returns:
        ToolContext: Cloned per tool dispatch inside ``run_b_turn``.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_tool_context_for_turn)
        True
    """
    voice_rt = channel_router._voice_rt
    checkout = resolve_sevn_checkout_for_workspace(
        workspace,
        content_root=layout.content_root,
    )
    configured = (
        (workspace.my_sevn.repo_path or "").strip() if workspace.my_sevn is not None else ""
    )
    if checkout is not None:
        logger.info(
            "sevn checkout (source_code/ mirror source)={} workspace={}",
            checkout.as_posix(),
            layout.content_root,
        )
    elif configured:
        logger.warning(
            "my_sevn.repo_path={} did not resolve to a checkout; "
            "source_code/ mirror will be empty until it is set",
            configured,
        )
    graphify_settings = effective_graphify_settings(workspace, checkout)
    profile_root = checkout if checkout is not None else layout.content_root
    graphify_profiles = (
        resolve_active_profiles_cached(graphify_settings, profile_root)
        if graphify_settings.enabled
        else []
    )
    known_tool_names = frozenset(td.name for td in (*tool_set.native, *tool_set.mcp))
    from sevn.workspace.artifact_output import artifact_output_prefix

    output_prefix = artifact_output_prefix(workspace, session_id)
    return ToolContext(
        session_id=session_id,
        workspace_path=layout.content_root,
        workspace_id=workspace.workspace_root or str(layout.content_root),
        registry_version=tool_set.registry_version,
        checkout_path=checkout,
        trace=trace,
        permissions=_permission_policy_from_workspace(
            workspace,
            channel=channel,
            user_id=outbound_user_id,
        ),
        sandbox_client=runtime_bindings.sandbox,
        channel_adapter=channel_adapter,
        channel_router=channel_router,
        outbound_user_id=outbound_user_id,
        outbound_metadata=dict(outbound_metadata),
        tts_pipeline=channel_router._tts,
        voice_tts_voice_id=voice_rt.tts_voice_id,
        turn_id=correlation_id,
        turn_span_id=turn_span_id,
        delivery_channel=channel,
        graphify_profiles=graphify_profiles,
        plugin_hooks=plugin_hooks,
        known_tool_names=known_tool_names,
        tool_debug_result_max_chars=tool_debug_result_max_chars(workspace),
        artifact_output_prefix=output_prefix,
    )


def _plugin_hooks_from_router(router: ChannelRouter) -> Any | None:
    """Return the router's plugin hook chain when wired at boot.
    Args:
        router (ChannelRouter): Gateway router constructed with optional hooks.
    Returns:
        Any | None: ``PluginHookChain`` or ``None`` when unset.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_plugin_hooks_from_router)
        True
    """
    return getattr(router, "_plugin_hook_chain", None)


def _apply_routing_footer_once(
    text: str,
    *,
    triage: TriageResult,
    triager_ms: int | None,
    enabled: bool,
    sent: bool,
) -> tuple[str, bool]:
    """Append routing footer to the first outbound bubble when enabled.

    Args:
        text (str): Assistant-visible text.
        triage (TriageResult): Triage decision for the turn.
        triager_ms (int | None): Triager latency in milliseconds for footer metadata.
        enabled (bool): Whether ``telegram.show_routing`` is on for this channel.
        sent (bool): Whether footer was already attached this turn.

    Returns:
        tuple[str, bool]: Annotated text and whether footer was applied.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_apply_routing_footer_once)
        True
    """
    if not enabled or sent or not text.strip():
        return text, False
    from sevn.gateway.routing_footer import append_routing_footer

    return append_routing_footer(text, triage, triager_ms=triager_ms), True


def _apply_tier_b_grounding_guard(
    text: str,
    outcome: Any,
    *,
    bound_tools: frozenset[str] | None = None,
    steer_buffer: SteerInject | None = None,
) -> tuple[str, str | None]:
    """Apply tier-B grounding guards to outbound text when warranted.

    Args:
        text (str): Candidate outbound text after preamble stripping.
        outcome (Any): Tier-B ``BTurnOutcome`` when available.
        bound_tools (frozenset[str] | None): Triager-bound tool names for W2 coverage.
        steer_buffer (SteerInject | None): Optional steer queue for forced retries.

    Returns:
        tuple[str, str | None]: ``(text, block_reason)`` — ``block_reason`` is a machine
        label when delivery must be blocked (e.g. ``tool_unavailable_claim``).

    Examples:
        >>> from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload
        >>> claim = "Cron is in src/sevn/tools/cron/runner.py"
        >>> out = BTurnOutcome(
        ...     status="completed",
        ...     final_messages=(ChannelPayload(text=claim),),
        ...     escalation=None,
        ...     rounds_used=0,
        ... )
        >>> guarded, block_reason = _apply_tier_b_grounding_guard(claim, out)
        >>> block_reason is None
        True
        >>> guarded.startswith("**Unverified**")
        True
    """
    if outcome is None:
        return text, None
    grounding_tools: frozenset[str] = frozenset(
        getattr(outcome, "grounding_tools_called", frozenset()),
    )
    tools = bound_tools or frozenset()
    unavailable_tool = claims_bound_tool_unavailable(text, tools)
    if unavailable_tool and unavailable_tool not in grounding_tools and tools:
        if steer_buffer is not None:
            steer_buffer.inject_pending(steer_for_direct_tool_call(unavailable_tool))
        logger.info(
            "tier_b.grounding_guard_blocked tool={} rounds_used={}",
            unavailable_tool,
            getattr(outcome, "rounds_used", None),
        )
        return "", "tool_unavailable_claim"
    successful_tools: frozenset[str] = frozenset(
        getattr(outcome, "successful_tools_called", frozenset()),
    )
    guarded, file_blocked = apply_file_delivery_grounding_guard(
        text,
        successful_tools_called=successful_tools,
        had_tool_failures=getattr(outcome, "had_tool_failures", False),
    )
    if file_blocked:
        logger.info(
            "tier_b.grounding_guard_blocked reason=fabricated_file_delivery rounds_used={} "
            "successful_tools={} had_tool_failures={}",
            getattr(outcome, "rounds_used", None),
            sorted(successful_tools),
            getattr(outcome, "had_tool_failures", False),
        )
        return "", "fabricated_file_delivery"
    guarded, applied = apply_zero_tool_grounding_guard(
        guarded,
        grounding_tools_called=grounding_tools,
    )
    if applied:
        logger.info(
            "tier_b.grounding_guard_applied rounds_used={} grounding_tools={}",
            getattr(outcome, "rounds_used", None),
            sorted(grounding_tools),
        )
    codemode_trace: frozenset[str] = frozenset(
        getattr(outcome, "codemode_bound_tools_called", frozenset()),
    )
    tools_attempted: frozenset[str] = frozenset(
        getattr(outcome, "tools_attempted", frozenset()),
    )
    guarded, audit_applied = apply_audit_evidence_guard(
        guarded,
        successful_tools=successful_tools,
        codemode_bound_tools_called=codemode_trace,
        tools_attempted=tools_attempted,
    )
    if audit_applied:
        effective_evidence = (successful_tools | codemode_trace) & EVIDENCE_TOOLS
        logger.info(
            "tier_b.audit_evidence_guard_applied rounds_used={} evidence_tools={}",
            getattr(outcome, "rounds_used", None),
            sorted(effective_evidence),
        )
    return guarded, None


def _deliverable_assistant_text(text: str | None) -> str | None:
    """Return stripped assistant text when it should be sent or persisted.

    Filters blank bodies and the internal ``(no output)`` executor placeholder
    so empty turns fall through to typed no-answer handling instead of leaving
    junk rows in ``gateway_messages``.

    Args:
        text (str | None): Raw assistant payload text.

    Returns:
        str | None: Non-empty deliverable text, or ``None`` when absent/placeholder.

    Examples:
        >>> _deliverable_assistant_text("  hello  ")
        'hello'
        >>> _deliverable_assistant_text("(no output)") is None
        True
    """
    stripped = (text or "").strip()
    if not stripped or stripped == ASSISTANT_NO_OUTPUT_PLACEHOLDER:
        return None
    return stripped


def _is_triager_opener_ack(text: str) -> bool:
    """Whether ``first_message`` is a short in-flight ack (P9 duplicate-opener guard).

    Args:
        text (str): Triager ``first_message`` for the turn.

    Returns:
        bool: ``True`` when the line is an opener-style ack, not substantive content.

    Examples:
        >>> _is_triager_opener_ack("On it — running the full pipeline.")
        True
        >>> _is_triager_opener_ack("Here is the full registry list:")
        False
    """
    return is_bare_opener(text)


def _strip_preamble_echo(text: str, preamble: str) -> str:
    """Strip a leading near-duplicate of the triager preamble from tier-B output.

    Delegates to :func:`sevn.agent.openers.strip_opener_echo` so the gateway and
    harness share one algorithm.

    Args:
        text (str): Tier-B output (already concatenated across messages).
        preamble (str): The triager's ``first_message`` for this turn.

    Returns:
        str: ``text`` with a leading echo of ``preamble`` removed.

    Examples:
        >>> _strip_preamble_echo("On it — checking now.\\n\\nHere's the answer.", "On it — checking now.")
        "Here's the answer."
        >>> _strip_preamble_echo("Here's the answer.", "On it — checking now.")
        "Here's the answer."
    """
    return strip_opener_echo(text, preamble)


def _merge_provider_turn_metadata(
    metadata: dict[str, Any],
    outcome: BTurnOutcome,
) -> dict[str, Any]:
    """Attach structured provider history for workspace persistence (D8).

    Args:
        metadata (dict[str, Any]): Outbound routing metadata.
        outcome (BTurnOutcome): Completed tier-B outcome.

    Returns:
        dict[str, Any]: Copy of ``metadata`` with ``provider_turn_messages`` when present.

    Examples:
        >>> from sevn.agent.executors.b_types import BTurnOutcome, ChannelPayload
        >>> merged = _merge_provider_turn_metadata(
        ...     {"chat_id": 1},
        ...     BTurnOutcome(
        ...         status="completed",
        ...         final_messages=(ChannelPayload(text="ok"),),
        ...         escalation=None,
        ...         rounds_used=1,
        ...         provider_turn_messages=({"role": "user", "content": "hi"},),
        ...     ),
        ... )
        >>> PROVIDER_TURN_MESSAGES_KEY in merged
        True
    """
    if not outcome.provider_turn_messages:
        return metadata
    merged = dict(metadata)
    merged[PROVIDER_TURN_MESSAGES_KEY] = list(outcome.provider_turn_messages)
    if outcome.successful_tools_called:
        merged[SUCCESSFUL_TOOLS_KEY] = sorted(outcome.successful_tools_called)
    return merged


def _outbound_phase_for_assistant_chunk(
    *,
    had_triager_first: bool,
    index: int,
    total: int,
) -> str:
    """Pick Telegram progressive-send phase for one assistant chunk.

    Triager ``first_message`` uses ``persist`` and is never the stream anchor.
    Executor chunks may use ``early`` / ``continue`` / ``final`` on their own bubble.

    Args:
        had_triager_first (bool): Whether Triager ``first_message`` was sent as ``persist``.
        index (int): Zero-based index in the final chunk list.
        total (int): Number of final chunks.

    Returns:
        str: ``early``, ``continue``, ``final``, or ``persist`` for :data:`GATEWAY_OUTBOUND_PHASE_KEY`.

    Examples:
        >>> _outbound_phase_for_assistant_chunk(had_triager_first=False, index=0, total=1)
        'final'
        >>> _outbound_phase_for_assistant_chunk(had_triager_first=True, index=0, total=1)
        'final'
        >>> _outbound_phase_for_assistant_chunk(had_triager_first=False, index=0, total=2)
        'early'
        >>> _outbound_phase_for_assistant_chunk(had_triager_first=True, index=1, total=2)
        'final'
    """
    if total <= 0:
        return "final"
    if total == 1:
        return "final"
    if index == 0:
        return "early"
    if index == total - 1:
        return "final"
    return "continue"


async def _route_assistant_text(
    router: ChannelRouter,
    channel: str,
    user_id: str,
    session_id: str,
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    outbound_phase: str | None = None,
) -> None:
    """Deliver one assistant line via ``route_outgoing``.
    Args:
        router (ChannelRouter): Gateway router.
        channel (str): Target channel key.
        user_id (str): Destination user id.
        session_id (str): Owning session id.
        text (str): Assistant-visible text.
        metadata (dict[str, Any] | None): Optional adapter routing hints.
        outbound_phase (str | None): Telegram progressive phase when set.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_route_assistant_text)
        True
    """
    meta = dict(metadata or {})
    if outbound_phase and channel == "telegram":
        meta[GATEWAY_OUTBOUND_PHASE_KEY] = outbound_phase
    await router.route_outgoing(
        OutgoingMessage(
            channel=channel,
            user_id=user_id,
            text=text,
            session_id=session_id,
            metadata=meta,
        ),
    )


async def _emit_gateway_span(
    trace: TraceSink,
    *,
    kind: str,
    session_id: str,
    turn_id: str,
    status: str,
    attrs: dict[str, object],
    span_id: str | None = None,
) -> None:
    """Emit a structured trace event when a sink is configured.
    Args:
        trace (TraceSink): Gateway trace sink (may be null).
        kind (str): Span kind string.
        session_id (str): Session id.
        turn_id (str): Correlation / turn id.
        status (str): Span status label.
        attrs (dict[str, object]): Attribute payload.
        span_id (str | None): Optional fixed span id (defaults to random hex).
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_gateway_span)
        True
    """
    if trace is None:
        return
    from sevn.agent.tracing.sink import TraceEvent

    now = time_ns()
    await trace.emit(
        TraceEvent(
            kind=kind,
            span_id=span_id or uuid.uuid4().hex,
            parent_span_id=None,
            session_id=session_id,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs=dict(attrs),
        ),
    )
