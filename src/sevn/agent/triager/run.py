"""Triager orchestration (`specs/13-rlm-triager.md` §2, §6).
Module: sevn.agent.triager.run
Depends: asyncio, sevn.agent.providers.resolve, sevn.agent.triager.context,
    sevn.agent.triager.errors, sevn.agent.triager.models,
    sevn.agent.triager.prompt, sevn.config.defaults, sevn.config.workspace_config
Exports:
    Functions:
        effective_triager_config — typed knobs with defaults applied.
        resolve_triager_model_id — pick primary text model id (§2.6).
        resolve_triager_model_id_for_turn — main or cheap triager model (§2.6).
        resolve_triager_transport_name — infer transport from providers merge.
        permissions_scope_narrowing_enabled — read narrowing toggle (§2.4).
        StructuredOutputCallResult — segment timings from structured LLM call.
        structured_output_call — live pydantic-ai structured Triager LLM call.
        extract_json_payload — strip markdown fences around JSON.
        finalize_triage_result — caps, filtering, coerce rules (§2.2-§2.4).
        should_inject_group_triage_block — decide §4.1 block injection.
        triage_turn — async facade returning validated ``TriageResult``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, time_ns
from typing import TYPE_CHECKING, Any, Final

import httpx
from loguru import logger
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelResponsePart

from sevn.agent.adapters import tier_b_model
from sevn.agent.adapters.native_model import (
    default_native_model_context,
    resolve_pydantic_model_for_slot,
)
from sevn.agent.adapters.tier_b_model import build_tier_b_function_model
from sevn.agent.adapters.tool_part_filter import filter_tool_call_parts
from sevn.agent.executors.b_types import ResolvedTierBModel
from sevn.agent.persona import load_persona_block
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.resolve import resolve_model
from sevn.agent.providers.transport_http import TransportBadRequest
from sevn.agent.tracing.otel_pipeline import instrumentation_capability
from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.agent.tracing.trace_event_bridge import attach_turn_trace_context
from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
    Workspace,
)
from sevn.agent.triager.errors import TriagerUnavailable, TriagerUnknownToolAbort
from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
from sevn.agent.triager.prompt import (
    TRIAGER_PROMPT_VERSION,
    build_triager_prompt_segments,
    concat_prompt_for_stub_llm,
)
from sevn.agent.triager.routing_policy import (
    apply_routing_policy,
    default_early_ack,
    is_obvious_continuation_message,
    is_strict_greeting_message,
    try_fast_continuation_triage,
    try_fast_greeting_triage,
)
from sevn.code_understanding.triager_orientation import (
    infer_orientation_intent,
    orientation_block_for_workspace,
)
from sevn.config.defaults import (
    DEFAULT_TRIAGER_TIMEOUT_HARD_S,
    TRIAGER_PYDANTIC_OUTPUT_RETRIES,
)
from sevn.config.llm_params import resolve_effective_max_output_tokens
from sevn.config.model_resolution import (
    ModelSlot,
    native_model_enabled,
    resolve_main_model_id,
    resolve_transport_for_model_id,
)
from sevn.config.sections.providers import providers_section_dict
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import TriagerWorkspaceConfig
from sevn.logging.structured import debug_event, preview

_DEFAULT_STUB_JSON: Final[str] = json.dumps(
    {
        "intent": "NEW_REQUEST",
        "complexity": "B",
        "first_message": "(stub Triager)",
        "tools": [],
        "skills": [],
        "mcp_servers_required": [],
        "confidence": 0.5,
        "requires_vision": False,
        "requires_document": False,
        "disregard": False,
    },
)


def _is_empty_output_retry_error(exc: BaseException) -> bool:
    """Return True when pydantic-ai exhausted retries on empty model output (W5).

    Args:
        exc (BaseException): Error raised from ``agent.run``.

    Returns:
        bool: True when the message signals ``maximum output retries``.

    Examples:
        >>> _is_empty_output_retry_error(RuntimeError("Exceeded maximum output retries (3)"))
        True
        >>> _is_empty_output_retry_error(ValueError("bad json"))
        False
    """
    return "maximum output retries" in str(exc).lower()


def _triager_budget_regime() -> str:
    """Return the Triager ``ModelBudget`` regime label for trace attrs.

    Returns:
        str: ``BudgetRegime.PER_TOKEN`` value (§2.6 default posture).

    Examples:
        >>> _triager_budget_regime() == BudgetRegime.PER_TOKEN.value
        True
    """
    return BudgetRegime.PER_TOKEN.value


async def _emit_triage_span(
    trace: TraceSink | None,
    *,
    kind: str,
    session_id: str,
    turn_id: str,
    parent_span_id: str | None,
    status: str,
    attrs: dict[str, object],
) -> None:
    """Emit one Triager lifecycle span when a sink is configured.

    Args:
        trace (TraceSink | None): Gateway trace sink.
        kind (str): Span kind (``triage.start``, ``triage.complete``, ``triage.error``).
        session_id (str): Owning session id.
        turn_id (str): Turn correlation id.
        parent_span_id (str | None): Turn root span id for parent linkage.
        status (str): Span status label.
        attrs (dict[str, object]): Redaction-safe attributes (no raw prompts).

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_emit_triage_span(None, kind="triage.start", session_id="s",
        ...     turn_id="t", parent_span_id=None, status="started", attrs={})) is None
        True
    """
    if trace is None:
        return
    now = time_ns()
    await trace.emit(
        TraceEvent(
            kind=kind,
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            session_id=session_id,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs=dict(attrs),
        ),
    )


def effective_triager_config(workspace: Workspace) -> TriagerWorkspaceConfig:
    """Return typed triager knobs with defaults.
    Args:
        workspace (Workspace): Validated workspace config.
    Returns:
        TriagerWorkspaceConfig: ``workspace.triager`` when present, else a
        default-constructed ``TriagerWorkspaceConfig``.
    Examples:
        >>> ws = Workspace.minimal()
        >>> cfg = effective_triager_config(ws)
        >>> isinstance(cfg, TriagerWorkspaceConfig)
        True
    """
    return workspace.triager if workspace.triager is not None else TriagerWorkspaceConfig()


def _hard_timeout_s(cfg: TriagerWorkspaceConfig) -> float:
    """Resolve the hard timeout in seconds for a Triager call.
    Args:
        cfg (TriagerWorkspaceConfig): Triager subtree of workspace config.
    Returns:
        float: ``cfg.timeout.hard_s`` when set, else ``DEFAULT_TRIAGER_TIMEOUT_HARD_S``.
    Examples:
        >>> _hard_timeout_s(TriagerWorkspaceConfig()) == float(DEFAULT_TRIAGER_TIMEOUT_HARD_S)
        True
    """
    t = cfg.timeout
    if t is None:
        return DEFAULT_TRIAGER_TIMEOUT_HARD_S
    return float(t.hard_s)


def _use_stub_transport() -> bool:
    """Use canned JSON only when ``SEVN_TRIAGER_STUB=1`` (CI / eval replay fixtures).
    Unset or any value other than ``1``/``true``/``yes``/``on`` uses the live pydantic-ai path.
    Returns:
        bool: True when the stub transport should be used.
    Examples:
        >>> isinstance(_use_stub_transport(), bool)
        True
    """
    raw = os.environ.get("SEVN_TRIAGER_STUB", "0")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def resolve_triager_model_id_for_turn(
    workspace: Workspace,
    *,
    triage_context: TriagePromptContext,
    triager_cfg: TriagerWorkspaceConfig,
) -> str:
    """Pick triager model id for this turn (main or optional cheap continuation model).

    When ``triager.cheap_model_id`` is set and the user message is an obvious
    short continuation, route triage through the cheaper model while tier-B/C/D
    executors keep their own ``providers.tier_default`` slots.

    Args:
        workspace (Workspace): Validated workspace config.
        triage_context (TriagePromptContext): Per-call suffix inputs.
        triager_cfg (TriagerWorkspaceConfig): Resolved triager knobs.

    Returns:
        str: Model id for the structured triage LLM call.

    Examples:
        >>> ws = Workspace.minimal(
        ...     providers={"tier_default": {"triager": "minimax/MiniMax-M3"}},
        ...     triager={"cheap_model_id": "anthropic:claude-3-5-haiku"},
        ... )
        >>> ctx = TriagePromptContext(current_message="go ahead")
        >>> resolve_triager_model_id_for_turn(ws, triage_context=ctx, triager_cfg=ws.triager)
        'anthropic:claude-3-5-haiku'
    """
    cheap = triager_cfg.cheap_model_id
    if (
        cheap
        and cheap.strip()
        and is_obvious_continuation_message(triage_context.current_message)
        and not triage_context.is_first_session
        and not triage_context.bootstrap_capture_active
    ):
        return cheap.strip()
    return resolve_triager_model_id(workspace)


def resolve_triager_model_id(workspace: Workspace) -> str:
    """Pick primary text ``model_id`` from ``providers.tier_default.triager`` (`specs/13` §2.6).
    Args:
        workspace (Workspace): Validated workspace config.
    Returns:
        str: Stripped model id string.
    Raises:
        TriagerUnavailable: When the providers map is missing the triager entry
            or it is not a non-empty string.
    Examples:
        >>> ws = Workspace.minimal(
        ...     providers={"tier_default": {"triager": "openai:gpt-4o-mini"}},
        ... )
        >>> resolve_triager_model_id(ws)
        'openai:gpt-4o-mini'
    """
    return resolve_main_model_id(workspace)


def resolve_triager_transport_name(providers_obj: dict[str, Any], model_id: str) -> str:
    """Infer transport label from merged ``providers.models[model_id]`` or default.
    Args:
        providers_obj (dict[str, Any]): Merged ``providers`` block from workspace.
        model_id (str): Model id to look up in ``providers_obj['models']``.
    Returns:
        str: Lowercased transport name, defaulting to ``"chat_completions"``.
    Examples:
        >>> resolve_triager_transport_name({}, "x")
        'chat_completions'
        >>> resolve_triager_transport_name(
        ...     {"models": {"x": {"transport": "Responses"}}}, "x"
        ... )
        'responses'
    """
    return resolve_transport_for_model_id(providers_obj, model_id)


def permissions_scope_narrowing_enabled(workspace: Workspace) -> bool:
    """Read ``permissions.scope_narrowing.enabled`` (`specs/13` §2.4).
    Args:
        workspace (Workspace): Validated workspace config.
    Returns:
        bool: True when scope narrowing may be emitted by the Triager.
    Examples:
        >>> ws = Workspace.minimal()
        >>> permissions_scope_narrowing_enabled(ws)
        False
        >>> ws2 = Workspace.minimal(
        ...     permissions={"scope_narrowing": {"enabled": True}},
        ... )
        >>> permissions_scope_narrowing_enabled(ws2)
        True
    """
    perms = workspace.permissions if isinstance(workspace.permissions, dict) else {}
    narrow = perms.get("scope_narrowing")
    if isinstance(narrow, dict):
        return bool(narrow.get("enabled"))
    return False


_STRUCTURED_OUTPUT_ALLOWED_TOOLS: Final[frozenset[str]] = frozenset({"final_result"})

# D7 / W4B: Tier A is greetings/thanks/bye/smalltalk only — never substantive answers.
_TIER_A_ALLOWED_INTENTS: Final[frozenset[Intent]] = frozenset({Intent.GREETING})
_TIER_A_FIRST_MESSAGE_MAX_CHARS: Final[int] = 100
_TIER_A_BULLET_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*•]\s+\S", re.M)
_TIER_A_NUMBERED_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*\d+[.)]\s+\S", re.M)
_TIER_A_TABLE_LINE: Final[re.Pattern[str]] = re.compile(r"\|.+\|")
_TIER_A_LINK: Final[re.Pattern[str]] = re.compile(r"https?://|\bwww\.", re.I)
_TIER_A_FENCED_CODE: Final[re.Pattern[str]] = re.compile(r"```")


def _filter_structured_output_tool_parts(
    parts: list[ModelResponsePart],
    *,
    allowed_tool_names: frozenset[str] = _STRUCTURED_OUTPUT_ALLOWED_TOOLS,
) -> list[ModelResponsePart]:
    """Drop recovered tool calls unknown to a structured-output-only agent.

    The triager exposes only pydantic-ai's ``final_result`` tool
    (``function_tools=[]``). MiniMax XML recovery must not surface ``load_skill``
    or other hallucinated names as ``ToolCallPart`` — that yields
    ``RetryPromptPart`` payloads the proxy rejects with HTTP 400.

    Delegates to :func:`sevn.agent.adapters.tool_part_filter.filter_tool_call_parts`;
    kept as a wrapper so the ``_structured_output_xml_recovery_guard`` API is stable.

    Args:
        parts (list[ModelResponsePart]): Post-conversion assistant parts.
        allowed_tool_names (frozenset[str]): Tool names pydantic-ai may execute.

    Returns:
        list[ModelResponsePart]: Parts with unknown ``ToolCallPart`` entries removed.

    Examples:
        >>> from pydantic_ai.messages import TextPart, ToolCallPart
        >>> kept = _filter_structured_output_tool_parts([
        ...     TextPart(content="hi"),
        ...     ToolCallPart(tool_name="load_skill", args="{}", tool_call_id="1"),
        ... ])
        >>> [type(p).__name__ for p in kept]
        ['TextPart']
    """
    return filter_tool_call_parts(
        parts, allowed_tool_names=allowed_tool_names, log_prefix="triager"
    )


@contextlib.contextmanager
def _structured_output_xml_recovery_guard() -> Iterator[None]:
    """Patch MiniMax XML recovery so the triager never emits unknown tool calls.

    Yields:
        None: While the patched recovery is active.

    Returns:
        collections.abc.Iterator[None]: Context manager that restores the original
        recovery on exit.

    Examples:
        >>> with _structured_output_xml_recovery_guard():
        ...     pass
    """
    original = tier_b_model._apply_xml_tool_recovery

    def _guarded(parts: list[ModelResponsePart]) -> list[ModelResponsePart]:
        return _filter_structured_output_tool_parts(original(parts))

    tier_b_model._apply_xml_tool_recovery = _guarded
    try:
        yield
    finally:
        tier_b_model._apply_xml_tool_recovery = original


@dataclass(frozen=True, slots=True)
class StructuredOutputCallResult:
    """Segment timings from ``structured_output_call`` (`specs/13` §2.6, §7).

    Args:
        json (str): JSON string for ``TriageResult.model_validate_json``.
        prep_ms (float): Persona load + ``Agent`` construction (ms, one decimal).
        model_ms (float): ``await agent.run(user_prompt)`` wall time (ms).
        serialize_ms (float): ``model_dump_json()`` time (ms).
        model_request_count (int | None): pydantic-ai usage requests when available.
    Examples:
        >>> StructuredOutputCallResult(json='{}', prep_ms=1.0, model_ms=2.0, serialize_ms=0.1)
        StructuredOutputCallResult(json='{}', prep_ms=1.0, model_ms=2.0, serialize_ms=0.1, model_request_count=None)
    """

    json: str
    prep_ms: float
    model_ms: float
    serialize_ms: float
    model_request_count: int | None = None


async def structured_output_call(
    *,
    workspace: Workspace,
    model_id: str,
    transport_name: str,
    user_prompt: str,
    seed: int | None,
    content_root: Path | None = None,
    turn_span_id: str | None = None,
    trace: TraceSink | None = None,
    session_id: str = "triager",
    turn_id: str = "triager",
) -> StructuredOutputCallResult:
    """Run pydantic-ai structured output for ``TriageResult`` (`specs/13` §2.7).
    Args:
        workspace (Workspace): Validated workspace config (native-model flag).
        model_id (str): Resolved triager model id (e.g. ``"openai:gpt-4o-mini"``).
        transport_name (str): Transport label (``chat_completions``, ``anthropic``, etc.).
        user_prompt (str): Concatenated prompt blob for the Triager pass.
        seed (int | None): Optional deterministic seed fallback when the workspace
            params file omits ``seed``; ``None`` to omit.
        content_root (Path | None): Workspace content root for persona ``system_prompt``
            and ``LLM_params_config.json`` sampling lookup.
        turn_span_id (str | None): Optional turn root span id for trace parent linkage.
        trace (TraceSink | None): Optional trace sink for native-model checkpoints.
        session_id (str): Session id for native-model trace correlation.
        turn_id (str): Turn id for native-model trace correlation.
    Returns:
        StructuredOutputCallResult: JSON payload plus segment timings for trace attrs.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(structured_output_call)
        True
    """
    prep_started_at = monotonic()
    _, transport = resolve_model(model_id=model_id, transport_name=transport_name)
    effective_max_output_tokens = resolve_effective_max_output_tokens(
        "triager",
        model_id,
        workspace,
        content_root=content_root,
    )
    bundle = ResolvedTierBModel(
        model_id=model_id,
        transport=transport,
        budget=ModelBudget(model_id=model_id, regime=BudgetRegime.PER_TOKEN),
    )
    # W7.4: sampling params come solely from LLM_params_config.json via the resolver.
    function_model = build_tier_b_function_model(
        bundle=bundle,
        steer_buffer=None,
        trace=trace,
        session_id=session_id,
        turn_id=turn_id,
        provider_round_counter=[0],
        agent="triager",
        content_root=content_root,
        seed=seed,
        max_output_tokens=effective_max_output_tokens,
    )
    if native_model_enabled(workspace, ModelSlot.triager):
        providers_obj = providers_section_dict(workspace.providers)
        proxy_base = ProcessSettings().proxy_url or "http://127.0.0.1:8787"
        native_ctx = default_native_model_context(
            slot=ModelSlot.triager,
            model_id=model_id,
            proxy_base=proxy_base,
            session_id=session_id,
            turn_id=turn_id,
            agent="triager",
            trace=trace,
            tier="A",
            parent_span_id=turn_span_id,
            content_root=content_root,
            seed=seed,
            max_output_tokens=effective_max_output_tokens,
            providers_obj=providers_obj,
        )
        model = resolve_pydantic_model_for_slot(workspace=workspace, ctx=native_ctx)
    else:
        model = function_model
    persona_root = content_root if content_root is not None else Path(".")
    system_prompt = (
        load_persona_block(persona_root) + "\n\nOutput only valid JSON conforming to TriageResult."
    )
    # Transport-layer empty-content nudge (W5) handles one MiniMax blank ``end_turn``
    # before pydantic-ai's retry budget; keep output retries low so repeated empties
    # fall through to the triager synthetic fallback quickly.
    agent = Agent(
        model=model,
        output_type=TriageResult,
        system_prompt=system_prompt,
        retries=TRIAGER_PYDANTIC_OUTPUT_RETRIES,
        capabilities=[instrumentation_capability()],
    )
    model_started_at = monotonic()
    prep_ms = round((model_started_at - prep_started_at) * 1000.0, 1)
    with _structured_output_xml_recovery_guard(), attach_turn_trace_context(turn_span_id):
        result = await agent.run(user_prompt)
    serialize_started_at = monotonic()
    model_ms = round((serialize_started_at - model_started_at) * 1000.0, 1)
    json_payload = result.output.model_dump_json()
    serialize_ms = round((monotonic() - serialize_started_at) * 1000.0, 1)
    model_request_count: int | None = None
    with contextlib.suppress(Exception):
        model_request_count = result.usage.requests
    return StructuredOutputCallResult(
        json=json_payload,
        prep_ms=prep_ms,
        model_ms=model_ms,
        serialize_ms=serialize_ms,
        model_request_count=model_request_count,
    )


def _read_stub_fixture_path(raw_path: str) -> str:
    """Load a stub Triager response fixture from disk.
    Args:
        raw_path (str): Path string (env-var/expanduser expansion is applied).
    Returns:
        str: Stripped file contents (already JSON-shaped).
    Raises:
        TriagerUnavailable: When the fixture file is empty.
    Examples:
        >>> import inspect
        >>> inspect.signature(_read_stub_fixture_path).return_annotation
        'str'
    """
    path = Path(os.path.expanduser(os.path.expandvars(raw_path.strip())))
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        msg = f"stub fixture {path} is empty"
        raise TriagerUnavailable(msg)
    return text


def _stub_response_json() -> str:
    """Return a stub JSON body for the Triager response.
    Resolution order: ``SEVN_TRIAGER_STUB_FIXTURE_PATH`` (file contents) →
    ``SEVN_TRIAGER_STUB_JSON`` (inline body) → built-in default.
    Returns:
        str: JSON-shaped text suitable for ``TriageResult.model_validate_json``.
    Examples:
        >>> body = _stub_response_json()
        >>> '"intent"' in body
        True
    """
    raw_path = os.environ.get("SEVN_TRIAGER_STUB_FIXTURE_PATH")
    if raw_path:
        return _read_stub_fixture_path(raw_path)
    body = os.environ.get("SEVN_TRIAGER_STUB_JSON")
    return body.strip() if body and body.strip() else _DEFAULT_STUB_JSON


def extract_json_payload(text: str) -> str:
    """Strip markdown fences around a JSON object if present.
    Args:
        text (str): Raw LLM output, possibly wrapped in `````json`` fences.
    Returns:
        str: Fence-stripped, leading/trailing-whitespace-stripped body.
    Examples:
        >>> extract_json_payload('```json\\n{"a": 1}\\n```')
        '{"a": 1}'
        >>> extract_json_payload('  {"b": 2}  ')
        '{"b": 2}'
    """
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        inner: list[str] = []
        for line in lines[1:]:
            if line.strip().startswith("```"):
                break
            inner.append(line)
        s = "\n".join(inner).strip()
    return s


def _deterministic_triage_fallback_from_raw(
    raw_text: str,
    *,
    turn_id: str,
) -> TriageResult | None:
    """Best-effort parse of partial triager JSON before synthetic downgrade (P10).

    Args:
        raw_text (str): Raw model output (may include fences or XML noise).
        turn_id (str): Correlation id for rotating the default early ack line.

    Returns:
        TriageResult | None: Parsed row when JSON validates; ``None`` otherwise.

    Examples:
        >>> r = _deterministic_triage_fallback_from_raw(
        ...     '{"intent":"NEW_REQUEST","complexity":"B","first_message":"On it.",'
        ...     '"tools":[],"skills":[],"mcp_servers_required":[],"confidence":0.8,'
        ...     '"requires_vision":false,"requires_document":false,"disregard":false}',
        ...     turn_id="t",
        ... )
        >>> r is not None and r.intent == Intent.NEW_REQUEST
        True
    """
    cleaned = extract_json_payload(raw_text)
    if not cleaned.strip():
        return None
    try:
        return TriageResult.model_validate_json(cleaned)
    except (json.JSONDecodeError, ValidationError, ValueError):
        return None


def _synthetic_schema_fallback(*, turn_id: str = "") -> TriageResult:
    """L1b synthetic downgrade (`specs/13` §6); tier B with mandatory early ack.

    Args:
        turn_id (str): Correlation id for rotating the default early ack line.

    Returns:
        TriageResult: Synthetic NEW_REQUEST/tier-B result with non-empty first_message.
    Examples:
        >>> r = _synthetic_schema_fallback(turn_id="f")
        >>> r.intent
        <Intent.NEW_REQUEST: 'NEW_REQUEST'>
        >>> r.complexity
        <ComplexityTier.B: 'B'>
        >>> bool(r.first_message.strip())
        True
    """
    return TriageResult.model_construct(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message=default_early_ack(turn_id=turn_id),
        tools=[],
        skills=[],
        mcp_servers_required=[],
        confidence=0.55,
        requires_vision=False,
        requires_document=False,
        disregard=False,
        followup_anchor=None,
        permission_scope_narrowing=None,
    )


def _apply_attachment_modality_flags(
    result: TriageResult,
    *,
    attachment_hints: list[dict[str, str]],
) -> TriageResult:
    """Set ``requires_vision`` / ``requires_document`` from inbound attachment hints.

    Merges heuristic inference with any values the Triager LLM already emitted
    so image/PDF turns always carry modality flags end-to-end (W9).

    Args:
        result (TriageResult): Parsed or fast-path triage output.
        attachment_hints (list[dict[str, str]]): ``ApprovedUserTurn`` attachment rows.

    Returns:
        TriageResult: Copy with modality flags OR-ed with inferred values.

    Examples:
        >>> from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
        >>> base = TriageResult(
        ...     intent=Intent.NEW_REQUEST,
        ...     complexity=ComplexityTier.B,
        ...     first_message="ok",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.5,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> out = _apply_attachment_modality_flags(
        ...     base,
        ...     attachment_hints=[{"kind": "photo", "media_type": "image/png", "name": "a.png"}],
        ... )
        >>> out.requires_vision
        True
    """
    if not attachment_hints:
        return result
    requires_vision = result.requires_vision
    requires_document = result.requires_document
    for hint in attachment_hints:
        kind = str(hint.get("kind") or "").casefold()
        media_type = str(hint.get("media_type") or "").casefold()
        name = str(hint.get("name") or "").casefold()
        if kind in {"photo", "image"} or media_type.startswith("image/"):
            requires_vision = True
        if kind == "document" and (media_type == "application/pdf" or name.endswith(".pdf")):
            requires_document = True
    if requires_vision == result.requires_vision and requires_document == result.requires_document:
        return result
    return result.model_copy(
        update={
            "requires_vision": requires_vision,
            "requires_document": requires_document,
        },
    )


def _coerce_disregard_model_violation(
    result: TriageResult,
    *,
    policy: str,
) -> TriageResult:
    """Normalize disregard oddities (`specs/13` §6 bottom row).
    Args:
        result (TriageResult): Parsed triage result.
        policy (str): ``triager.disregard_non_a_complexity`` (``"coerce"`` /
            ``"abort"``).
    Returns:
        TriageResult: Result with ``complexity`` coerced to ``A`` when
            ``disregard`` is true under ``"coerce"`` policy; otherwise unchanged.
    Raises:
        TriagerUnavailable: When the policy is ``"abort"`` and ``disregard`` is
            set with a non-A complexity.
    Examples:
        >>> r = TriageResult(
        ...     intent=Intent.GREETING,
        ...     complexity=ComplexityTier.A,
        ...     first_message="hi",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.5,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> _coerce_disregard_model_violation(r, policy="coerce") is r
        True
    """
    if policy == "abort":
        msg = "disregard set with complexity other than A and policy is abort"
        raise TriagerUnavailable(msg)
    if result.disregard and result.complexity != ComplexityTier.A:
        logger.warning(
            "triager: coercing complexity to A because disregard=true and complexity!=A (`specs/13` §6)",
        )
        return result.model_copy(update={"complexity": ComplexityTier.A})
    return result


def _filter_identifiers(
    values: list[str],
    *,
    allowed: set[str],
    policy: str,
    kind: str,
    other_kind_allowed: set[str] | None = None,
    other_kind: str | None = None,
) -> tuple[list[str], list[str]]:
    """Drop identifiers not in ``allowed`` per the configured policy.

    When ``other_kind_allowed`` is supplied and an ``item`` belongs to that other
    category (e.g. an LLM-emitted ``skill`` id appearing under ``tools``), the id
    is **moved** to a separate "recovered" list rather than silently dropped. The
    caller is expected to merge recovered ids into the correct list, log
    ``triager.recovered_misplaced_<kind>`` for each move, and **never** double-count.

    Args:
        values (list[str]): Candidate identifiers emitted by the model.
        allowed (set[str]): Registry-known identifiers for this ``kind``.
        policy (str): ``"strip"`` (warn + drop) or ``"abort"`` (raise).
        kind (str): Human label for logs/errors (``"tool"``, ``"skill"``, ...).
        other_kind_allowed (set[str] | None): Ids from the sibling category; an
            item present here is moved to the recovered list instead of dropped.
        other_kind (str | None): Human label for the sibling category.

    Returns:
        tuple[list[str], list[str]]: ``(kept, recovered)`` — ``kept`` is the
            normal in-category list; ``recovered`` contains ids that belong to
            the sibling category and should be merged there by the caller.

    Raises:
        TriagerUnknownToolAbort: When ``policy == "abort"`` and an unknown id
            is encountered.

    Examples:
        >>> _filter_identifiers(["a", "b"], allowed={"a"}, policy="strip", kind="tool")
        (['a'], [])
        >>> _filter_identifiers(
        ...     ["lcm"], allowed=set(), policy="strip", kind="tool",
        ...     other_kind_allowed={"lcm"}, other_kind="skill",
        ... )
        ([], ['lcm'])
    """
    kept: list[str] = []
    recovered: list[str] = []
    for item in values:
        if item in allowed:
            kept.append(item)
            continue
        if other_kind_allowed is not None and item in other_kind_allowed:
            logger.warning(
                "triager.recovered_misplaced_{}: {} (belongs in {})",
                kind,
                item,
                other_kind or "other",
            )
            recovered.append(item)
            continue
        if policy == "abort":
            msg = f"unknown {kind} id {item!r} (`triager.on_unknown_named_tool=abort`)"
            raise TriagerUnknownToolAbort(msg)
        logger.warning("triager.filtered_unknown_{}: {}", kind, item)
    return kept, recovered


def _apply_tier_b_caps(result: TriageResult, caps: tuple[int, int], mode: str) -> TriageResult:
    """Cap Tier-B ``tools`` / ``skills`` lists per workspace caps.
    Args:
        result (TriageResult): Parsed result to cap.
        caps (tuple[int, int]): ``(tool_cap, skill_cap)`` pair.
        mode (str): Truncation mode (``"tail"`` / ``"score"``); ``"score"`` falls
            back to ``"tail"`` because per-item scores are absent (§2.3).
    Returns:
        TriageResult: Original instance when not Tier-B or under caps; a copy
            with truncated lists otherwise.
    Examples:
        >>> r = TriageResult(
        ...     intent=Intent.NEW_REQUEST,
        ...     complexity=ComplexityTier.B,
        ...     first_message="ok",
        ...     tools=["a", "b", "c"],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.5,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> _apply_tier_b_caps(r, (2, 5), "tail").tools
        ['a', 'b']
    """
    tcap, scap = caps
    tools = result.tools[:]
    skills = result.skills[:]
    if result.complexity != ComplexityTier.B:
        return result
    if mode not in {"tail", "score"}:
        mode = "tail"
    _ = mode  # score ranking lacks per-item scores §2.3 — keep declaration order (“tail”).
    changed = False
    if len(tools) > tcap:
        tools = tools[:tcap]
        changed = True
    if len(skills) > scap:
        skills = skills[:scap]
        changed = True
    if not changed:
        return result
    return result.model_copy(update={"tools": tools, "skills": skills})


def _tier_a_first_message_shape_overstepped(text: str) -> bool:
    """Return True when ``first_message`` looks like a substantive answer (D7).

    Tier-A ``first_message`` must be a one-line opener/ack — not tables, lists,
    code fences, links, or multi-paragraph prose.

    Args:
        text (str): Triager ``first_message`` after strip.

    Returns:
        bool: True when shape/length signals a tier-B answer.

    Examples:
        >>> _tier_a_first_message_shape_overstepped("Hi! What's up?")
        False
        >>> _tier_a_first_message_shape_overstepped("- item one\\n- item two")
        True
    """
    if not text.strip():
        return False
    if len(text) > _TIER_A_FIRST_MESSAGE_MAX_CHARS:
        return True
    if "\n\n" in text:
        return True
    if _TIER_A_FENCED_CODE.search(text):
        return True
    if _TIER_A_BULLET_LINE.search(text):
        return True
    if _TIER_A_NUMBERED_LINE.search(text):
        return True
    if _TIER_A_TABLE_LINE.search(text):
        return True
    return _TIER_A_LINK.search(text) is not None


def _apply_tier_a_scope_guard(
    result: TriageResult,
    *,
    current_message: str,
    turn_id: str = "",
) -> tuple[TriageResult, bool]:
    """Force-route invalid tier-A decisions to tier B (`specs/13` §2.2, D7).

    Tier A is allowed only for strict greeting/thanks/bye/smalltalk with a
    short, single-line ``first_message``. Any substantive intent, non-greeting
    user message, or over-long/structured opener escalates to tier B.

    Skipped when ``SEVN_TRIAGER_EVAL_REPLAY=1`` (golden eval injects labels verbatim;
    synthetic corpus rows are not production utterances).

    Args:
        result (TriageResult): Post-routing-policy triage output.
        current_message (str): Latest user message for greeting detection.
        turn_id (str): Correlation id for early-ack rotation.

    Returns:
        tuple[TriageResult, bool]: Adjusted result and whether an override fired.

    Examples:
        >>> r = TriageResult(
        ...     intent=Intent.NEW_REQUEST,
        ...     complexity=ComplexityTier.A,
        ...     first_message="Here is the full answer about cron.",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.9,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> out, over = _apply_tier_a_scope_guard(r, current_message="where is cron?")
        >>> over and out.complexity == ComplexityTier.B
        True
    """
    if os.environ.get("SEVN_TRIAGER_EVAL_REPLAY", "").strip().lower() in ("1", "true", "yes"):
        return result, False
    if result.disregard or result.complexity != ComplexityTier.A:
        return result, False
    msg = current_message.strip()
    shape_bad = _tier_a_first_message_shape_overstepped(result.first_message)
    intent_bad = result.intent not in _TIER_A_ALLOWED_INTENTS
    greeting_bad = bool(msg) and not is_strict_greeting_message(msg)
    if not (intent_bad or greeting_bad or shape_bad):
        return result, False
    logger.warning(
        "triager_overstepped intent={} shape_bad={} greeting_bad={} len={}",
        result.intent.value,
        shape_bad,
        greeting_bad,
        len(result.first_message),
    )
    updates: dict[str, object] = {
        "complexity": ComplexityTier.B,
        "first_message": default_early_ack(turn_id=turn_id),
    }
    if intent_bad or greeting_bad:
        updates["intent"] = Intent.NEW_REQUEST
    return result.model_copy(update=updates), True


def finalize_triage_result(
    *,
    parsed: TriageResult,
    registry_snapshot: RegistrySnapshot,
    session: SessionView,
    workspace: Workspace,
    triager_cfg: TriagerWorkspaceConfig,
    triage_context: TriagePromptContext | None = None,
    trace_attrs: dict[str, object] | None = None,
    operator_name: str | None = None,
) -> TriageResult:
    """Tier-B caps, registry filtering, permissions, coerce rules (`specs/13` §2.2-§2.4).
    Args:
        parsed (TriageResult): Parsed Triager result from the LLM.
        registry_snapshot (RegistrySnapshot): Allowed tool/skill/MCP ids.
        session (SessionView): Session-scoped MCP enablement set.
        workspace (Workspace): Workspace config (permissions, narrowing).
        triager_cfg (TriagerWorkspaceConfig): Resolved triager knobs.
        triage_context (TriagePromptContext | None): Per-call context for routing policy.
        trace_attrs (dict[str, object] | None): Optional sink attrs populated when
            tier-A scope overrides fire (``triager_overstepped``).
        operator_name (str | None): Preferred name from ``USER.md`` for tier-A replies.
    Returns:
        TriageResult: Validated, filtered, and capped result.
    Raises:
        TriagerUnavailable: When invariants fail (e.g. Tier-A non-disregard
            with empty ``first_message``) or coerce policy aborts.
        TriagerUnknownToolAbort: When an unknown tool/skill/MCP id is rejected
            under ``"abort"`` policy.
    Examples:
        >>> r = TriageResult(
        ...     intent=Intent.NEW_REQUEST,
        ...     complexity=ComplexityTier.B,
        ...     first_message="ok",
        ...     tools=[],
        ...     skills=[],
        ...     mcp_servers_required=[],
        ...     confidence=0.5,
        ...     requires_vision=False,
        ...     requires_document=False,
        ... )
        >>> out = finalize_triage_result(
        ...     parsed=r,
        ...     registry_snapshot=RegistrySnapshot(),
        ...     session=SessionView(session_id="s"),
        ...     workspace=Workspace.minimal(),
        ...     triager_cfg=TriagerWorkspaceConfig(),
        ... )
        >>> out.complexity
        <ComplexityTier.B: 'B'>
    """
    if not permissions_scope_narrowing_enabled(workspace) and parsed.permission_scope_narrowing:
        parsed = parsed.model_copy(update={"permission_scope_narrowing": None})
    tool_ids = {e.identifier for e in registry_snapshot.tools}
    skill_ids = {e.identifier for e in registry_snapshot.skills}
    mcp_ids = {e.identifier for e in registry_snapshot.mcp_servers}
    enabled_session = set(session.mcp_enabled_servers)
    policy = triager_cfg.on_unknown_named_tool
    tools, tools_recovered_as_skills = _filter_identifiers(
        parsed.tools,
        allowed=tool_ids,
        policy=policy,
        kind="tool",
        other_kind_allowed=skill_ids,
        other_kind="skill",
    )
    skills, skills_recovered_as_tools = _filter_identifiers(
        parsed.skills,
        allowed=skill_ids,
        policy=policy,
        kind="skill",
        other_kind_allowed=tool_ids,
        other_kind="tool",
    )
    # Merge recovered ids into the correct list while preserving order and dedup.
    for ident in tools_recovered_as_skills:
        if ident not in skills:
            skills.append(ident)
    for ident in skills_recovered_as_tools:
        if ident not in tools:
            tools.append(ident)
    filtered_mcp: list[str] = []
    for srv in parsed.mcp_servers_required:
        if srv not in mcp_ids:
            if policy == "abort":
                msg = f"unknown MCP server id {srv!r}"
                raise TriagerUnknownToolAbort(msg)
            logger.warning("triager.filtered_unknown_mcp: {}", srv)
            continue
        if enabled_session and srv not in enabled_session:
            if policy == "abort":
                msg = f"MCP server {srv!r} not enabled for this session"
                raise TriagerUnknownToolAbort(msg)
            logger.warning("triager.filtered_mcp_not_enabled_session: {}", srv)
            continue
        filtered_mcp.append(srv)
    interim = parsed.model_copy(
        update={
            "tools": tools,
            "skills": skills,
            "mcp_servers_required": filtered_mcp,
        },
    )
    interim = _coerce_disregard_model_violation(
        interim,
        policy=triager_cfg.disregard_non_a_complexity,
    )
    caps = (triager_cfg.tier_b_tool_cap, triager_cfg.tier_b_skill_cap)
    interim = _apply_tier_b_caps(interim, caps, triager_cfg.tier_b_truncation)
    if (
        interim.complexity == ComplexityTier.A
        and not interim.disregard
        and not interim.first_message.strip()
    ):
        msg = "tier A responses require non-empty first_message (`specs/13` §2.2)"
        raise TriagerUnavailable(msg)
    _ = TRIAGER_PROMPT_VERSION  # reserved for triager span attrs (`specs/13` §7)
    current = triage_context.current_message if triage_context is not None else ""
    turn_id = triage_context.turn_id if triage_context is not None else ""
    is_first = triage_context.is_first_session if triage_context is not None else False
    bootstrap_active = (
        triage_context.bootstrap_capture_active if triage_context is not None else False
    )
    routed = apply_routing_policy(
        interim,
        current_message=current,
        turn_id=turn_id,
        is_first_session=is_first,
        bootstrap_capture_active=bootstrap_active,
        operator_name=operator_name,
        indexed_skill_ids=frozenset(skill_ids),
        complexity_clamp_confidence_threshold=triager_cfg.complexity_clamp_confidence_threshold,
        complexity_clamp_short_word_limit=triager_cfg.complexity_clamp_short_word_limit,
    )
    guarded, overstepped = _apply_tier_a_scope_guard(
        routed,
        current_message=current,
        turn_id=turn_id,
    )
    if overstepped and trace_attrs is not None:
        trace_attrs["triager_overstepped"] = True
    return guarded


def should_inject_group_triage_block(
    *,
    workspace: Workspace,
    session: SessionView,
    base_context: TriagePromptContext,
) -> bool:
    """Return True when §4.1 English block belongs in the suffix (`specs/13` §4.1).
    Args:
        workspace (Workspace): Workspace config (triager.group_scope).
        session (SessionView): Session view (chat_member_count).
        base_context (TriagePromptContext): Base context whose pre-set flag
            short-circuits decision when already true.
    Returns:
        bool: True when the §4.1 block must be appended to the suffix.
    Examples:
        >>> ws = Workspace.minimal()
        >>> sv = SessionView(session_id="s", chat_member_count=2)
        >>> ctx = TriagePromptContext(current_message="hi")
        >>> should_inject_group_triage_block(
        ...     workspace=ws, session=sv, base_context=ctx
        ... )
        True
    """
    if base_context.inject_group_triage_block:
        return True
    cfg = effective_triager_config(workspace)
    if cfg.group_scope != "all":
        return False
    return session.chat_member_count > 1


async def triage_turn(
    *,
    workspace: Workspace,
    session: SessionView,
    incoming: ApprovedUserTurn,
    registry_snapshot: RegistrySnapshot,
    triage_context: TriagePromptContext,
    content_root: Path | None = None,
    trace: TraceSink | None = None,
    turn_span_id: str | None = None,
) -> TriageResult:
    """Run one structured routing pass (`specs/13` §2).
    Args:
        workspace (Workspace): Validated workspace config.
        session (SessionView): Narrow session slice (member count, MCP set).
        incoming (ApprovedUserTurn): Scanner-approved user payload (currently
            not directly inlined into the prompt; gateway pre-folds hints into
            ``triage_context``).
        registry_snapshot (RegistrySnapshot): Tool/skill/MCP catalogue slice.
        triage_context (TriagePromptContext): Per-call suffix inputs.
        content_root (Path | None): Workspace content root for persona ``system_prompt``.
        trace (TraceSink | None): Optional gateway trace sink for ``triage.*`` spans.
        turn_span_id (str | None): Turn root span id (``gateway.turn.start`` parent).
    Returns:
        TriageResult: Validated and finalised triage result (after caps,
            filtering, and coercion rules).
    Raises:
        TriagerUnavailable: When fatal policy violations occur (e.g. abort on
            unknown tools when the policy says so, missing first_message for
            Tier-A non-disregard, or unrecoverable provider failure).
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(triage_turn)
        True
    """
    _ = incoming  # attachment hints merged into ``triage_context`` below.
    # Wall-clock start for the per-turn triage latency field on ``triager.output``
    # (`specs/13-rlm-triager.md` §7). Lightweight observability — a pure greeting
    # short-circuit lands in single-digit ms; a full LLM pass is seconds. ``fast_path``
    # distinguishes the canned tier-A route from the LLM route in logs/trace.
    started_at = monotonic()
    fast_path_used = False
    cfg = effective_triager_config(workspace)
    turn_id = triage_context.turn_id
    session_id = session.session_id
    operator_name = None
    if content_root is not None:
        from sevn.gateway.bootstrap_state import operator_name_from_user_md

        operator_name = operator_name_from_user_md(content_root)
    try:
        model_id = resolve_triager_model_id_for_turn(
            workspace,
            triage_context=triage_context,
            triager_cfg=cfg,
        )
    except TriagerUnavailable:
        model_id = "unknown"
    budget_regime = _triager_budget_regime()
    await _emit_triage_span(
        trace,
        kind="triage.start",
        session_id=session_id,
        turn_id=turn_id,
        parent_span_id=turn_span_id,
        status="started",
        attrs={
            "model_id": model_id,
            "budget_regime": budget_regime,
        },
    )

    async def _finish(
        result: TriageResult,
        *,
        error: str | None = None,
        extra_attrs: dict[str, object] | None = None,
    ) -> TriageResult:
        attrs: dict[str, object] = {
            "intent": result.intent.value,
            "complexity": result.complexity.value,
            "model_id": model_id,
            "budget_regime": budget_regime,
            "confidence": result.confidence,
        }
        if extra_attrs:
            attrs.update(extra_attrs)
        if error is not None:
            attrs["error"] = error
            await _emit_triage_span(
                trace,
                kind="triage.error",
                session_id=session_id,
                turn_id=turn_id,
                parent_span_id=turn_span_id,
                status="error",
                attrs=attrs,
            )
        await _emit_triage_span(
            trace,
            kind="triage.complete",
            session_id=session_id,
            turn_id=turn_id,
            parent_span_id=turn_span_id,
            status="error" if error else "ok",
            attrs=attrs,
        )
        return result

    async def _finalize_and_finish(
        parsed: TriageResult,
        *,
        error: str | None = None,
        raw: TriageResult | None = None,
        trace_attrs_extra: dict[str, object] | None = None,
    ) -> TriageResult:
        extra_attrs: dict[str, object] = dict(trace_attrs_extra or {})
        try:
            finalized = finalize_triage_result(
                parsed=parsed,
                registry_snapshot=registry_snapshot,
                session=session,
                workspace=workspace,
                triager_cfg=cfg,
                triage_context=triage_context,
                trace_attrs=extra_attrs,
                operator_name=operator_name,
            )
            finalized = _apply_attachment_modality_flags(
                finalized,
                attachment_hints=incoming.attachment_descriptors,
            )
        except TriagerUnavailable as exc:
            err_attrs: dict[str, object] = {
                "model_id": model_id,
                "budget_regime": budget_regime,
                "error": type(exc).__name__,
            }
            await _emit_triage_span(
                trace,
                kind="triage.error",
                session_id=session_id,
                turn_id=turn_id,
                parent_span_id=turn_span_id,
                status="error",
                attrs=err_attrs,
            )
            raise
        raw_for_log = raw if raw is not None else parsed
        elapsed_ms = round((monotonic() - started_at) * 1000.0, 1)
        debug_event(
            "triager.output",
            session_id=session_id,
            turn_id=turn_id,
            model_id=model_id,
            elapsed_ms=elapsed_ms,
            fast_path=fast_path_used,
            intent=finalized.intent.value,
            complexity=finalized.complexity.value,
            confidence=finalized.confidence,
            first_message=preview(finalized.first_message),
            raw_first_message=preview(raw_for_log.first_message),
            tools=list(finalized.tools),
            skills=list(finalized.skills),
            disregard=finalized.disregard,
        )
        return await _finish(finalized, error=error, extra_attrs=extra_attrs)

    if (
        cfg.fast_greeting_path
        and not triage_context.is_first_session
        and not triage_context.bootstrap_capture_active
    ):
        fast = try_fast_greeting_triage(
            current_message=triage_context.current_message,
            turn_id=turn_id,
            operator_name=operator_name,
        )
        if fast is not None:
            fast_path_used = True
            return await _finalize_and_finish(fast)
    if (
        cfg.fast_continuation_path
        and not triage_context.is_first_session
        and not triage_context.bootstrap_capture_active
        and triage_context.prior_triage_result is not None
    ):
        fast_cont = try_fast_continuation_triage(
            current_message=triage_context.current_message,
            prior=triage_context.prior_triage_result,
            turn_id=turn_id,
        )
        if fast_cont is not None:
            fast_path_used = True
            return await _finalize_and_finish(fast_cont)
    merged_ctx = triage_context.model_copy(
        update={
            "inject_group_triage_block": should_inject_group_triage_block(
                workspace=workspace,
                session=session,
                base_context=triage_context,
            ),
            "code_orientation_block": orientation_block_for_workspace(
                workspace,
                content_root=content_root,
                intent=infer_orientation_intent(triage_context.current_message),
            ),
            "attachment_hints": list(incoming.attachment_descriptors),
        },
    )
    segments = build_triager_prompt_segments(
        registry_snapshot=registry_snapshot,
        triage_context=merged_ctx,
    )
    user_blob = concat_prompt_for_stub_llm(segments)
    from sevn.agent.tracing.agent_context import build_triager_context_attrs, emit_context_span

    await emit_context_span(
        trace,
        kind="triager.context",
        session_id=session_id,
        turn_id=turn_id,
        parent_span_id=turn_span_id,
        tier=None,
        attrs=build_triager_context_attrs(
            segments=segments,
            current_message=merged_ctx.current_message,
            transcript_turns=merged_ctx.transcript_turns,
            registry_version=registry_snapshot.registry_version,
            personality_version=merged_ctx.personality_version,
            user_language=merged_ctx.user_language,
            attachment_hints=merged_ctx.attachment_hints,
            user_blob=user_blob,
        ),
    )
    timeout_s = _hard_timeout_s(cfg)
    relax_ctx = {"relax_greeting_lists": cfg.relax_greeting_lists}

    debug_event(
        "triager.input",
        session_id=session_id,
        turn_id=turn_id,
        model_id=model_id,
        transcript_turns=len(merged_ctx.transcript_turns),
        personality_version=merged_ctx.personality_version,
        current_message=preview(merged_ctx.current_message),
        registry_version=registry_snapshot.registry_version,
        is_first_session=merged_ctx.is_first_session,
    )

    structured_call_timing: dict[str, object] | None = None

    async def fetch_raw() -> str:
        nonlocal structured_call_timing
        if _use_stub_transport():
            return _stub_response_json()
        call_model_id = resolve_triager_model_id_for_turn(
            workspace,
            triage_context=merged_ctx,
            triager_cfg=cfg,
        )
        providers = providers_section_dict(workspace.providers)
        transport_name = resolve_triager_transport_name(providers, call_model_id)
        call_result = await structured_output_call(
            workspace=workspace,
            model_id=call_model_id,
            transport_name=transport_name,
            user_prompt=user_blob,
            seed=cfg.deterministic_seed,
            content_root=content_root,
            turn_span_id=turn_span_id,
            trace=trace,
            session_id=session_id,
            turn_id=turn_id,
        )
        structured_call_timing = {
            "prep_ms": call_result.prep_ms,
            "model_ms": call_result.model_ms,
            "serialize_ms": call_result.serialize_ms,
        }
        if call_result.model_request_count is not None:
            structured_call_timing["model_request_count"] = call_result.model_request_count
        return call_result.json

    parsed: TriageResult | None = None
    # Wave 3 (CONVERSATION_REVIEW_2026-05-28.md §A12): triager retry budget A=3.
    from sevn.config.defaults import TRIAGER_MAX_RETRY_ATTEMPTS

    raw_text = ""
    for attempt in range(TRIAGER_MAX_RETRY_ATTEMPTS):
        try:
            raw_text = await asyncio.wait_for(fetch_raw(), timeout=timeout_s)
            cleaned = extract_json_payload(raw_text)
            parsed = TriageResult.model_validate_json(cleaned, context=relax_ctx)
            break
        except TimeoutError:
            logger.warning("triager.hard_timeout after {}s (`specs/13` §6)", timeout_s)
            return await _finalize_and_finish(
                _synthetic_schema_fallback(turn_id=turn_id),
                error="hard_timeout",
            )
        except asyncio.CancelledError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            logger.warning("triager_schema_failure attempt {}: {}", attempt + 1, exc)
            recovered = _deterministic_triage_fallback_from_raw(raw_text, turn_id=turn_id)
            if recovered is not None:
                parsed = recovered
                break
            if attempt == 0:
                continue
            return await _finalize_and_finish(
                _synthetic_schema_fallback(turn_id=turn_id),
                error=type(exc).__name__,
            )
        except AgentRunError as exc:
            # Pydantic-AI gave up retrying — usually the model returned text in
            # a vendor-specific format (e.g. MiniMax's ``<minimax:tool_call>``
            # XML) that doesn't validate as TriageResult JSON. Fall back to the
            # synthetic schema so the turn still completes cleanly instead of
            # crashing the gateway.
            logger.warning("triager_agent_run_error attempt {}: {}", attempt + 1, exc)
            if _is_empty_output_retry_error(exc):
                return await _finalize_and_finish(
                    _synthetic_schema_fallback(turn_id=turn_id),
                    error=type(exc).__name__,
                    trace_attrs_extra={"empty_content_rate": 1.0},
                )
            if attempt == 0:
                continue
            return await _finalize_and_finish(
                _synthetic_schema_fallback(turn_id=turn_id),
                error=type(exc).__name__,
            )
        except NotImplementedError as exc:
            logger.warning("triager live path missing: {}", exc)
            if attempt == 0:
                continue
            return await _finalize_and_finish(
                _synthetic_schema_fallback(turn_id=turn_id),
                error=type(exc).__name__,
            )
        except (TransportBadRequest, httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "triager_transport_error attempt {}: {}",
                attempt + 1,
                exc,
            )
            if attempt == 0:
                continue
            return await _finalize_and_finish(
                _synthetic_schema_fallback(turn_id=turn_id),
                error=type(exc).__name__,
            )
    if parsed is None:
        return await _finalize_and_finish(
            _synthetic_schema_fallback(turn_id=turn_id),
            error="empty_parse",
        )
    return await _finalize_and_finish(
        parsed,
        raw=parsed,
        trace_attrs_extra=structured_call_timing,
    )
