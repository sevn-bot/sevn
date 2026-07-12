"""Tier C/D harness entry (`specs/21-executor-tier-cd.md` §2, §4).

Phases follow **decompose → PlanGate → RLM → synthesize** for ``dspy`` (outer transport
JSON contract) and **PlanGate → λ macro → synthesize** for ``lambda_rlm`` (no decompose).
``build_rlm_interpreter`` is imported **only** on the ``dspy`` execute path.

Module: sevn.agent.executors.cd_harness
Depends: sevn.agent.executors.*, sevn.agent.tracing,
    sevn.config.defaults, sevn.tools.*

Exports:
    run_cd_turn — C/D executor entrypoint.
    NoOpPlanGate — ``await_approval`` returns ``approved`` immediately (no trace).
    ImmediateApprovedPlanGate — same, optional trace emission on await.
    SupersedingPlanGate — test double returning ``superseded``.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(run_cd_turn)
    True
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from time import time_ns
from typing import Final, Literal, cast

from pydantic import ValidationError

from sevn.agent.executors.b_types import ChannelPayload, SessionHandle, SteerInject
from sevn.agent.executors.cd_types import (
    CdBackendLiteral,
    CdTurnOutcome,
    Plan,
    PlanGatePort,
    PlanStep,
    ResolvedCdOuterModels,
)
from sevn.agent.executors.lambda_rlm_runtime import run_lambda_rlm_turn
from sevn.agent.runtimes.sandbox import build_rlm_interpreter
from sevn.agent.tracing.provider_call import emit_provider_call
from sevn.agent.tracing.sink import TraceEvent, TraceSink, checkpoint_snapshot
from sevn.agent.triager.context import Workspace
from sevn.agent.triager.models import ComplexityTier, TriageResult
from sevn.config.defaults import (
    CD_OUTER_ROUNDS_MAX,
    CD_RLM_DEFAULT_MAX_LLM_CALLS,
    CD_RLM_MAX_ITERATIONS,
    CD_RLM_MAX_OUTPUT_CHARS,
    CD_SYNTH_MAX_CHARS,
    CD_SYNTH_MAX_TOKENS,
    DEFAULT_RLM_C_D_BACKEND,
    LAMBDA_RLM_DEGRADED_PLAN_SPLIT_MESSAGE,
)
from sevn.config.llm_params import resolve_effective_max_output_tokens, resolve_llm_request_params
from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.base import ToolExecutor
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy, apply_permission_scope_narrowing
from sevn.tools.registry import ToolSet


def _lambda_rlm_enabled(workspace: Workspace) -> bool:
    """Return whether ``executors.tier_cd.lambda_rlm.enabled`` is true.

    Args:
        workspace (Workspace): Loaded workspace config.

    Returns:
        bool: Opt-in λ-RLM gate (default **off**).

    Examples:
        >>> from unittest.mock import MagicMock
        >>> w = MagicMock()
        >>> w.executors = None
        >>> _lambda_rlm_enabled(w)
        False
    """

    executors = getattr(workspace, "executors", None)
    if executors is None:
        return False
    tier_cd = getattr(executors, "tier_cd", None)
    if tier_cd is None:
        return False
    lambda_rlm = getattr(tier_cd, "lambda_rlm", None)
    if lambda_rlm is None:
        return False
    return bool(getattr(lambda_rlm, "enabled", False))


def _cd_backend(workspace: Workspace) -> CdBackendLiteral:
    """Resolve C/D backend: ``dspy`` unless λ opt-in flag and ``rlm.c_d_backend`` agree.

    Args:
        workspace (Workspace): Loaded workspace config.

    Returns:
        CdBackendLiteral: ``dspy`` or ``lambda_rlm``.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from sevn.config.defaults import DEFAULT_RLM_C_D_BACKEND
        >>> w = MagicMock()
        >>> w.rlm = None
        >>> w.executors = None
        >>> _cd_backend(w) == DEFAULT_RLM_C_D_BACKEND
        True
    """

    if not _lambda_rlm_enabled(workspace):
        return "dspy"
    if workspace.rlm is None:
        return DEFAULT_RLM_C_D_BACKEND
    return workspace.rlm.c_d_backend


def _truncate_for_synth(text: str) -> str:
    """Bound execute-phase blob passed into ``SynthSig`` (§11 token cap).

    Args:
        text (str): Raw execute summary or partial RLM output.

    Returns:
        str: Text truncated to ``CD_SYNTH_MAX_CHARS`` when longer.

    Examples:
        >>> len(_truncate_for_synth("x" * 20_000)) <= 16384
        True
        >>> _truncate_for_synth("short")
        'short'
    """

    if len(text) <= CD_SYNTH_MAX_CHARS:
        return text
    return text[:CD_SYNTH_MAX_CHARS]


def _tool_set_names(tool_set: ToolSet) -> frozenset[str]:
    """Return every tool name exposed on the session snapshot.

    Args:
        tool_set (ToolSet): Session registry snapshot.

    Returns:
        frozenset[str]: Tool names from native and MCP entries.

    Examples:
        >>> from sevn.tools.registry import ToolSet
        >>> _tool_set_names(ToolSet(native=(), mcp=(), registry_version=1, skill_descriptions={}))
        frozenset()
    """

    return frozenset(d.name for d in (*tool_set.native, *tool_set.mcp))


def _leaf_allowed_count(workspace: Workspace, tool_set: ToolSet) -> int:
    """Count ``lambda_tool_allowlist`` entries that exist in ``tool_set`` (§2.5).

    Args:
        workspace (Workspace): Workspace with optional ``rlm`` block.
        tool_set (ToolSet): Session tool universe.

    Returns:
        int: Count of allowlisted names present in ``tool_set``.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from sevn.tools.registry import ToolSet
        >>> w = MagicMock()
        >>> w.rlm = None
        >>> _leaf_allowed_count(w, ToolSet(native=(), mcp=(), registry_version=1, skill_descriptions={}))
        0
    """

    if workspace.rlm is None:
        return 0
    allow = {str(x).strip() for x in workspace.rlm.lambda_tool_allowlist if str(x).strip()}
    return len(allow & _tool_set_names(tool_set))


def _lambda_allowlist_frozen(workspace: Workspace) -> frozenset[str]:
    """Normalised allowlist from workspace config.

    Args:
        workspace (Workspace): Workspace with optional ``rlm`` block.

    Returns:
        frozenset[str]: Stripped non-empty allowlist entries.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> w = MagicMock()
        >>> w.rlm = None
        >>> _lambda_allowlist_frozen(w) == frozenset()
        True
    """

    if workspace.rlm is None:
        return frozenset()
    return frozenset(str(x).strip() for x in workspace.rlm.lambda_tool_allowlist if str(x).strip())


def _merge_steer(base: str, steer: SteerInject | None) -> str:
    """Drain one pending ``/steer`` chunk into the task string (§4.6 minimal).

    Args:
        base (str): Original task text.
        steer (SteerInject | None): Optional steer buffer.

    Returns:
        str: Task text with any pending steer appended.

    Examples:
        >>> _merge_steer("task", None)
        'task'
    """

    if steer is None:
        return base
    extra = steer.pop_pending()
    if not extra:
        return base
    return f"{base}\n\n[/steer]: {extra}"


def _workspace_path(cfg: WorkspaceConfig) -> Path:
    """Resolve ``workspace_root`` to an absolute path (sync helper for async harness).

    Args:
        cfg (WorkspaceConfig): Workspace document.

    Returns:
        Path: Absolute filesystem root.

    Examples:
        >>> class _Cfg:
        ...     workspace_root = "/tmp/sevn_ws_doc"
        >>> _workspace_path(_Cfg()).name
        'sevn_ws_doc'
    """

    root = Path(cfg.workspace_root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


async def _emit(trace: TraceSink | None, event: TraceEvent) -> None:
    """Emit a trace event when a sink is configured.

    Args:
        trace (TraceSink | None): Optional sink.
        event (TraceEvent): Record to emit.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> from sevn.agent.tracing.sink import TraceEvent
        >>> asyncio.run(_emit(None, TraceEvent(
        ...     kind="x", span_id="s", parent_span_id=None, session_id="a",
        ...     turn_id="t", tier=None, ts_start_ns=0, ts_end_ns=0, status="ok", attrs={},
        ... ))) is None
        True
    """
    if trace is None:
        return
    await trace.emit(event)


def _assistant_text(response: dict[str, object]) -> str:
    """Best-effort assistant string from an OpenAI-shaped completion dict.

    Args:
        response (dict[str, object]): Parsed completion payload.

    Returns:
        str: Assistant ``content`` string, or ``"{}"`` when absent.

    Examples:
        >>> _assistant_text({"choices": [{"message": {"content": "hi"}}]})
        'hi'
        >>> _assistant_text({"content": "direct"})
        'direct'
        >>> _assistant_text({"content": [{"type": "text", "text": "anth"}]})
        'anth'
    """

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
    content_top = response.get("content")
    if isinstance(content_top, str):
        return content_top
    if isinstance(content_top, list):
        parts: list[str] = []
        for block in content_top:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        if parts:
            return "".join(parts)
    return "{}"


def _coerce_json_object(text: str) -> dict[str, object]:
    """Parse a JSON object from possibly fenced / prose-wrapped assistant text.

    Open models (e.g. ``minimax/*``) frequently wrap contract JSON in ```` ```json ````
    fences or precede it with reasoning prose, so a bare ``json.loads`` rejects valid
    plans. This tries, in order: a direct parse, a fence-stripped parse (shared with the
    triager's :func:`extract_json_payload`), and finally an outermost balanced-brace scan
    that is string/escape aware. Returns ``{}`` when no JSON object can be recovered.

    Args:
        text (str): Raw assistant text from the outer model.

    Returns:
        dict[str, object]: Parsed object, or ``{}`` when unrecoverable.

    Examples:
        >>> _coerce_json_object('{"steps": []}')
        {'steps': []}
        >>> _coerce_json_object('```json\\n{"steps": [1]}\\n```')
        {'steps': [1]}
        >>> _coerce_json_object('Here is the plan:\\n{"steps": []}\\nDone.')
        {'steps': []}
        >>> _coerce_json_object('no json here')
        {}
    """
    from sevn.agent.triager.run import extract_json_payload

    for candidate in (text, extract_json_payload(text), _outermost_json_object(text)):
        if not candidate:
            continue
        try:
            parsed: object = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return cast("dict[str, object]", parsed)
    return {}


def _outermost_json_object(text: str) -> str:
    """Return the first balanced ``{...}`` span in ``text``, or ``""`` if none.

    Scans for a top-level brace pair while ignoring braces inside JSON string
    literals (honouring backslash escapes), so embedded objects in prose survive.

    Args:
        text (str): Raw assistant text.

    Returns:
        str: The substring from the first ``{`` to its matching ``}``, else ``""``.

    Examples:
        >>> _outermost_json_object('x {"a": "}"} y')
        '{"a": "}"}'
        >>> _outermost_json_object('none')
        ''
    """
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


async def _transport_complete_json(
    *,
    transport: object,
    model_id: str,
    phase: str,
    payload: dict[str, object],
    trace: TraceSink | None = None,
    session_id: str = "",
    turn_id: str = "",
    tier: str | None = None,
    parent_span_id: str | None = None,
    budget_regime: str | None = None,
    content_root: Path | None = None,
    workspace: WorkspaceConfig | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    workspace_id: str | None = None,
    executor_tier: str | None = None,
) -> dict[str, object]:
    """POST one completion and parse JSON from assistant text.

    Args:
        transport (object): LLM transport implementing ``complete``.
        model_id (str): Outer model id.
        phase (str): Contract phase label embedded in the user message.
        payload (dict[str, object]): JSON-serialisable phase payload.
        trace (TraceSink | None): Optional trace sink for ``provider.*`` spans.
        session_id (str): Session attribute when tracing.
        turn_id (str): Turn attribute when tracing.
        tier (str | None): Harness tier label when tracing.
        parent_span_id (str | None): Turn root span for provider ``parent_span_id``.
        budget_regime (str | None): Budget regime label for provider span attrs.
        content_root (Path | None): Workspace content root for ``LLM_params_config.json``
            sampling lookup (agent ``tier_cd``); ``None`` uses built-in defaults.
        workspace (WorkspaceConfig | None): Parsed workspace for ``sevn.json`` max-output
            ceilings; ``None`` skips ceiling lookup.
        user_id (str | None): Channel user id for MiniMax ``metadata`` (D2).
        channel (str | None): Active channel key for MiniMax ``metadata`` (D2).
        workspace_id (str | None): Workspace id for MiniMax ``metadata`` (D2).
        executor_tier (str | None): Executor tier label for MiniMax ``metadata`` (D2).

    Returns:
        dict[str, object]: Parsed assistant JSON object, or ``{}`` on failure.

    Examples:
        >>> import asyncio
        >>> class _T:
        ...     name = "anthropic"
        ...     async def complete(self, req):
        ...         return {"choices": [{"message": {"content": "{}"}}]}
        ...     def tokens_used(self, raw):
        ...         return (0, 0)
        >>> asyncio.run(_transport_complete_json(
        ...     transport=_T(), model_id="m", phase="p", payload={"k": 1}))
        {}
    """

    from sevn.agent.adapters.tier_b_model import apply_minimax_anthropic_request_hygiene
    from sevn.agent.providers.transport import Transport
    from sevn.agent.providers.wire import adapt_request_for_transport

    t = cast("Transport", transport)
    vendor = getattr(t, "name", "unknown")
    provider_kind = f"provider.{vendor}.{model_id}"
    span_id = str(uuid.uuid4())
    start_ns = time_ns()
    provider_attrs: dict[str, object] = {
        "phase": phase,
        "model_id": model_id,
    }
    if budget_regime is not None:
        provider_attrs["budget_regime"] = budget_regime
    if trace is not None:
        await _emit(
            trace,
            TraceEvent(
                kind=provider_kind,
                span_id=span_id,
                parent_span_id=parent_span_id,
                session_id=session_id,
                turn_id=turn_id,
                tier=tier,
                ts_start_ns=start_ns,
                ts_end_ns=None,
                status="started",
                attrs=dict(provider_attrs),
            ),
        )
    # W7.4: tier_cd sampling from LLM_params_config.json (previously no temperature).
    # ``t.name`` is the resolved wire; params are filtered to that transport.
    sampling_kwargs = resolve_llm_request_params(
        "tier_cd", model_id, str(vendor), content_root=content_root
    )
    max_tokens = resolve_effective_max_output_tokens(
        "tier_cd", model_id, workspace, content_root=content_root
    )
    req: dict[str, object] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": json.dumps({"__sevn_cd_phase": phase, **payload}, sort_keys=True),
            }
        ],
        **sampling_kwargs,
    }
    apply_minimax_anthropic_request_hygiene(
        req,
        model_id=model_id,
        agent="tier_cd",
        content_root=content_root,
        has_tools=False,
        session_id=session_id or None,
        turn_id=turn_id or None,
        user_id=user_id,
        channel=channel,
        workspace_id=workspace_id,
        executor_tier=executor_tier,
    )
    try:
        raw = await t.complete(adapt_request_for_transport(t, req))
        in_tok, out_tok = t.tokens_used(raw)
    except BaseException as exc:
        end_ns = time_ns()
        if trace is not None:
            err_attrs = dict(provider_attrs)
            err_attrs["error"] = type(exc).__name__
            await _emit(
                trace,
                TraceEvent(
                    kind=provider_kind,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    tier=tier,
                    ts_start_ns=start_ns,
                    ts_end_ns=end_ns,
                    status="error",
                    attrs=err_attrs,
                ),
            )
        await emit_provider_call(
            trace,
            span_id=span_id,
            parent_span_id=parent_span_id,
            session_id=session_id,
            turn_id=turn_id,
            model_id=model_id,
            regime=budget_regime or "PER_TOKEN",
            tokens_in=0,
            tokens_out=0,
            transport=str(vendor),
            tier=tier,
            status="error",
            ts_start_ns=start_ns,
            ts_end_ns=end_ns,
            extra_attrs={"phase": phase, "error": type(exc).__name__},
        )
        raise
    text = _assistant_text(raw)
    result = _coerce_json_object(text)
    if trace is not None:
        ok_attrs = dict(provider_attrs)
        ok_attrs["input_tokens"] = in_tok
        ok_attrs["output_tokens"] = out_tok
        await _emit(
            trace,
            TraceEvent(
                kind=provider_kind,
                span_id=span_id,
                parent_span_id=parent_span_id,
                session_id=session_id,
                turn_id=turn_id,
                tier=tier,
                ts_start_ns=start_ns,
                ts_end_ns=time_ns(),
                status="ok",
                attrs=ok_attrs,
            ),
        )
    end_ns = time_ns()
    await emit_provider_call(
        trace,
        span_id=span_id,
        parent_span_id=parent_span_id,
        session_id=session_id,
        turn_id=turn_id,
        model_id=model_id,
        regime=budget_regime or "PER_TOKEN",
        tokens_in=in_tok,
        tokens_out=out_tok,
        transport=str(vendor),
        tier=tier,
        status="ok",
        ts_start_ns=start_ns,
        ts_end_ns=end_ns,
        extra_attrs={"phase": phase},
    )
    return result


class NoOpPlanGate:
    """PlanGate that approves immediately without persistence (§2.3)."""

    async def await_approval(
        self,
        *,
        plan: Plan,
        session_id: str,
        turn_id: str,
        trace: TraceSink | None,
    ) -> Literal["approved", "superseded"] | Plan:
        """Return ``approved``; ignore ``plan`` except for type surface.

        Args:
            plan (Plan): Pending plan artefact.
            session_id (str): Gateway session id.
            turn_id (str): Correlation id for tracing.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            Literal["approved", "superseded"] | Plan: Always ``approved`` here.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanStep
            >>> gate = NoOpPlanGate()
            >>> p = Plan(
            ...     steps=[PlanStep(id="1", title="t")],
            ...     summary="s",
            ...     meta=Plan.Meta(complexity="C", registry_version=1),
            ... )
            >>> asyncio.run(gate.await_approval(
            ...     plan=p, session_id="s", turn_id="t", trace=None))
            'approved'
        """

        _ = plan, session_id, turn_id, trace
        return "approved"


class ImmediateApprovedPlanGate:
    """PlanGate that approves immediately and emits ``plan_gate.await`` (tests / ops)."""

    async def await_approval(
        self,
        *,
        plan: Plan,
        session_id: str,
        turn_id: str,
        trace: TraceSink | None,
    ) -> Literal["approved", "superseded"] | Plan:
        """Emit a zero-duration await span then approve.

        Args:
            plan (Plan): Pending plan artefact.
            session_id (str): Gateway session id.
            turn_id (str): Correlation id for tracing.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            Literal["approved", "superseded"] | Plan: Always ``approved`` here.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanStep
            >>> gate = ImmediateApprovedPlanGate()
            >>> p = Plan(
            ...     steps=[PlanStep(id="1", title="t")],
            ...     summary="s",
            ...     meta=Plan.Meta(complexity="C", registry_version=1),
            ... )
            >>> asyncio.run(gate.await_approval(
            ...     plan=p, session_id="s", turn_id="t", trace=None))
            'approved'
        """

        sid = session_id
        tid = turn_id
        span = str(uuid.uuid4())
        now = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="plan_gate.await",
                span_id=span,
                parent_span_id=None,
                session_id=sid,
                turn_id=tid,
                tier=None,
                ts_start_ns=now,
                ts_end_ns=now,
                status="approved",
                attrs={"plan_summary_len": len(plan.summary)},
            ),
        )
        return "approved"


class SupersedingPlanGate:
    """Test double: always returns ``superseded``."""

    async def await_approval(
        self,
        *,
        plan: Plan,
        session_id: str,
        turn_id: str,
        trace: TraceSink | None,
    ) -> Literal["approved", "superseded"] | Plan:
        """Always yield ``superseded`` for harness tests.

        Args:
            plan (Plan): Pending plan artefact.
            session_id (str): Gateway session id.
            turn_id (str): Correlation id for tracing.
            trace (TraceSink | None): Optional trace sink.

        Returns:
            Literal["approved", "superseded"] | Plan: Always ``superseded``.

        Examples:
            >>> import asyncio
            >>> from sevn.agent.executors.cd_types import Plan, PlanStep
            >>> gate = SupersedingPlanGate()
            >>> p = Plan(
            ...     steps=[PlanStep(id="1", title="t")],
            ...     summary="s",
            ...     meta=Plan.Meta(complexity="C", registry_version=1),
            ... )
            >>> asyncio.run(gate.await_approval(
            ...     plan=p, session_id="s", turn_id="t", trace=None))
            'superseded'
        """
        _ = plan, session_id, turn_id, trace
        return "superseded"


def _default_plan_from_task(
    *,
    triage: TriageResult,
    incoming_text: str,
    tool_set: ToolSet,
) -> Plan:
    """Deterministic single-step plan used only for ``lambda_rlm`` (no DecomposeSig).

    Args:
        triage (TriageResult): Triager row with complexity **C** or **D**.
        incoming_text (str): User-visible task text.
        tool_set (ToolSet): Registry snapshot for metadata.

    Returns:
        Plan: Single-step plan wrapping the incoming title.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from sevn.agent.executors.cd_types import PlanStep
        >>> from sevn.agent.triager.models import ComplexityTier
        >>> from sevn.tools.registry import ToolSet
        >>> tr = MagicMock()
        >>> tr.complexity = ComplexityTier.C
        >>> p = _default_plan_from_task(
        ...     triage=tr,
        ...     incoming_text="hello",
        ...     tool_set=ToolSet(
        ...         native=(),
        ...         mcp=(),
        ...         registry_version=3,
        ...         skill_descriptions={},
        ...     ),
        ... )
        >>> p.steps[0].title
        'hello'
        >>> isinstance(p.steps[0], PlanStep)
        True
    """

    cx: Literal["C", "D"] = "C" if triage.complexity == ComplexityTier.C else "D"

    title = incoming_text.strip() or "(empty task)"
    return Plan(
        steps=[
            PlanStep(
                id="lambda-1",
                title=title[:240],
                tool_guess=None,
                requires_human=False,
            )
        ],
        summary=title[:2000],
        meta=Plan.Meta(complexity=cx, registry_version=tool_set.registry_version),
    )


def _decompose_has_usable_steps(dec: dict[str, object]) -> bool:
    """Return whether ``dec`` carries a non-empty ``steps`` list.

    Args:
        dec (dict[str, object]): Parsed decompose object.

    Returns:
        bool: ``True`` when ``steps`` is a non-empty list.

    Examples:
        >>> _decompose_has_usable_steps({"steps": [{"id": "1", "title": "t"}]})
        True
        >>> _decompose_has_usable_steps({"steps": []})
        False
        >>> _decompose_has_usable_steps({})
        False
    """
    steps = dec.get("steps")
    return isinstance(steps, list) and len(steps) > 0


def _wrap_decompose_as_single_step(
    dec: dict[str, object],
    *,
    triage: TriageResult,
    incoming_text: str,
    tool_set: ToolSet,
) -> dict[str, object] | None:
    """Coerce a missing-``steps`` decompose object into a single-step plan dict.

    Open models (e.g. ``minimax/*``) intermittently return a bare object with no
    ``steps`` wrapper, or leak unrelated JSON, into the decompose slot. Rather than
    failing the contract, treat any usable task text as a one-step plan so the C/D
    executor still runs — mirrors the tier-B MiniMax recovery in ``tier_b_model.py``
    (`specs/21-executor-tier-cd.md`). Returns ``None`` only when there is no task
    text at all to anchor the step on.

    Args:
        dec (dict[str, object]): Parsed decompose object lacking usable ``steps``.
        triage (TriageResult): Triager row (complexity C or D).
        incoming_text (str): User task text used as the single step title.
        tool_set (ToolSet): Registry snapshot for ``registry_version`` metadata.

    Returns:
        dict[str, object] | None: A plan dict validatable by :class:`Plan`, or
        ``None`` when no task text is available to wrap.

    Examples:
        >>> from unittest.mock import MagicMock
        >>> from sevn.agent.triager.models import ComplexityTier
        >>> from sevn.tools.registry import ToolSet
        >>> tr = MagicMock()
        >>> tr.complexity = ComplexityTier.C
        >>> ts = ToolSet(native=(), mcp=(), registry_version=2, skill_descriptions={})
        >>> out = _wrap_decompose_as_single_step(
        ...     {"thumbs_up": True}, triage=tr, incoming_text="fix all this",
        ...     tool_set=ts,
        ... )
        >>> out["steps"][0]["title"]
        'fix all this'
        >>> _wrap_decompose_as_single_step(
        ...     {}, triage=tr, incoming_text="   ", tool_set=ts,
        ... ) is None
        True
    """
    title = incoming_text.strip()
    if not title:
        summary_src = dec.get("summary")
        if isinstance(summary_src, str) and summary_src.strip():
            title = summary_src.strip()
    if not title:
        return None
    plan = _default_plan_from_task(
        triage=triage,
        incoming_text=title,
        tool_set=tool_set,
    )
    return cast("dict[str, object]", json.loads(plan.model_dump_json()))


_DECOMPOSE_JSON_ONLY_REPROMPT: Final[str] = (
    "Your previous reply did not contain a valid plan. Reply with ONLY a JSON object "
    'matching {"steps": [{"id": str, "title": str}], "summary": str, '
    '"meta": {"complexity": "C"|"D", "registry_version": int}} — no prose, no code '
    "fences, no other keys."
)


async def run_cd_turn(
    *,
    workspace: Workspace,
    session: SessionHandle,
    turn_id: str,
    triage: TriageResult,
    incoming_text: str,
    tool_set: ToolSet,
    body_cache: LoadedBodyCache,
    transport_outer: ResolvedCdOuterModels,
    trace: TraceSink | None,
    steer_buffer: SteerInject | None,
    plan_gate: PlanGatePort,
    tool_executor: ToolExecutor | None = None,
    tool_context: ToolContext | None = None,
) -> CdTurnOutcome:
    """Execute one C/D turn (``specs/21-executor-tier-cd.md`` §2.1).

    Args:
        workspace (Workspace): Parsed ``sevn.json`` (backend + allowlist + REPL lifetime).
        session (SessionHandle): Session identity for tracing.
        turn_id (str): Turn id shared with Triager spans.
        triage (TriageResult): Triager row with ``complexity`` **C** or **D**.
        incoming_text (str): User message body.
        tool_set (ToolSet): Session tool universe (§3.1).
        body_cache (LoadedBodyCache): Lazy body cache API surface (unused in v1 scaffold).
        transport_outer (ResolvedCdOuterModels): Outer + optional sub-LM transports.
        trace (TraceSink | None): Trace sink.
        steer_buffer (SteerInject | None): Optional ``/steer`` buffer (§4.6).
        plan_gate (PlanGatePort): Approval port.
        tool_executor (ToolExecutor | None): Registry for λ leaves; default empty executor.
        tool_context (ToolContext | None): Tool dispatch envelope; default permissive stub.

    Returns:
        CdTurnOutcome: Terminal disposition for the gateway.

    Raises:
        ValueError: When ``triage.complexity`` is not **C** or **D**.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_cd_turn)
        True
    """

    _ = body_cache
    if triage.complexity not in (ComplexityTier.C, ComplexityTier.D):
        msg = "run_cd_turn requires triage.complexity in {'C','D'}"
        raise ValueError(msg)

    if not isinstance(workspace, WorkspaceConfig):
        msg = "run_cd_turn expects WorkspaceConfig as workspace"
        raise TypeError(msg)

    # Workspace content root for LLM_params_config.json sampling lookup (W7.4).
    cd_content_root = _workspace_path(workspace)

    triager_first_reply = (triage.first_message or "").strip()

    backend = _cd_backend(workspace)
    steer = steer_buffer or SteerInject()
    exe = tool_executor or ToolExecutor(default_timeout_seconds=60.0)
    base_ctx = tool_context
    if base_ctx is None:
        root = _workspace_path(workspace)
        base_ctx = ToolContext(
            session_id=session.session_id,
            workspace_path=root,
            workspace_id="workspace",
            registry_version=tool_set.registry_version,
            trace=trace,
            permissions=AllowAllPermissionPolicy(),
            turn_id=turn_id,
            executor_tier="C" if triage.complexity == ComplexityTier.C else "D",
        )
    narrowed = apply_permission_scope_narrowing(
        base_ctx.permissions,
        triage.permission_scope_narrowing,
    )
    tool_ctx = replace(
        base_ctx,
        registry_version=tool_set.registry_version,
        permissions=narrowed,
        outbound_metadata=dict(base_ctx.outbound_metadata),
        turn_id=turn_id,
        executor_tier="C" if triage.complexity == ComplexityTier.C else "D",
    )
    cd_llm_user_id = tool_ctx.outbound_user_id or None
    cd_llm_channel = tool_ctx.delivery_channel or None
    cd_llm_workspace_id = tool_ctx.workspace_id or None
    cd_llm_executor_tier = tool_ctx.executor_tier

    parent = str(uuid.uuid4())
    turn_root = tool_ctx.turn_span_id
    outer_budget_regime = transport_outer.outer_budget.regime.value
    sub_budget_regime = (
        transport_outer.sub_lm_budget.regime.value
        if transport_outer.sub_lm_budget is not None
        else outer_budget_regime
    )
    provider_parent = turn_root
    t0 = time_ns()
    leaf_n = _leaf_allowed_count(workspace, tool_set)
    await _emit(
        trace,
        TraceEvent(
            kind="cd.turn",
            span_id=parent,
            parent_span_id=turn_root,
            session_id=session.session_id,
            turn_id=turn_id,
            tier=str(triage.complexity.value),
            ts_start_ns=t0,
            ts_end_ns=None,
            status="started",
            attrs={
                "c_d.backend": backend,
                "c_d.leaf_allowed_count": leaf_n,
            },
        ),
    )

    await _emit(
        trace,
        TraceEvent(
            kind="cd.backend",
            span_id=str(uuid.uuid4()),
            parent_span_id=parent,
            session_id=session.session_id,
            turn_id=turn_id,
            tier=str(triage.complexity.value),
            ts_start_ns=t0,
            ts_end_ns=t0,
            status="ok",
            attrs={"backend": backend},
        ),
    )

    rounds_outer_used = 0
    inner_exhausted = False
    inner_llm_total = 0

    try:
        if backend == "lambda_rlm":
            plan0 = _default_plan_from_task(
                triage=triage,
                incoming_text=incoming_text,
                tool_set=tool_set,
            )
            await checkpoint_snapshot(
                trace,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                kind="cd.lambda.plan_ready",
                excerpt=f"plan_steps={len(plan0.steps)} degraded_plan_split=true",
                state={"plan": plan0.model_dump(mode="json")},
            )
            await _emit(
                trace,
                TraceEvent(
                    kind="cd.lambda.degraded",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=parent,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    ts_start_ns=time_ns(),
                    ts_end_ns=time_ns(),
                    status="ok",
                    attrs={"message": LAMBDA_RLM_DEGRADED_PLAN_SPLIT_MESSAGE},
                ),
            )
        else:
            d0 = time_ns()
            await _emit(
                trace,
                TraceEvent(
                    kind="cd.decompose",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=parent,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    ts_start_ns=d0,
                    ts_end_ns=None,
                    status="started",
                    attrs={},
                ),
            )
            dec_body = _merge_steer(incoming_text, steer)
            if triager_first_reply:
                dec_body = (
                    f"{dec_body}\n\n"
                    "Triager opener already delivered to the user (do not repeat or "
                    f"contradict; build on it):\n  >>> {triager_first_reply}"
                )
            dec_payload: dict[str, object] = {
                "task": dec_body,
                "complexity": triage.complexity.value,
                "registry_version": tool_set.registry_version,
                "max_output_chars": CD_RLM_MAX_OUTPUT_CHARS,
                "max_iterations": CD_RLM_MAX_ITERATIONS,
                "max_llm_calls": CD_RLM_DEFAULT_MAX_LLM_CALLS,
            }
            if triager_first_reply:
                dec_payload["triager_first_reply"] = triager_first_reply
            dec = await _transport_complete_json(
                transport=transport_outer.outer_transport,
                model_id=transport_outer.outer_model_id,
                phase="decompose",
                payload=dec_payload,
                trace=trace,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                parent_span_id=provider_parent,
                budget_regime=outer_budget_regime,
                content_root=cd_content_root,
                user_id=cd_llm_user_id,
                channel=cd_llm_channel,
                workspace_id=cd_llm_workspace_id,
                executor_tier=cd_llm_executor_tier,
                workspace=workspace,
            )
            # MiniMax recovery (`specs/21-executor-tier-cd.md`): open models intermittently
            # emit ``{}`` or unrelated JSON into the decompose slot. Re-prompt once with an
            # explicit JSON-only instruction, then — failing that — wrap any usable task
            # text as a single-step plan before declaring the contract dead.
            decompose_recovery = ""
            if not _decompose_has_usable_steps(dec):
                reprompt_payload = dict(dec_payload)
                reprompt_payload["repair_instruction"] = _DECOMPOSE_JSON_ONLY_REPROMPT
                dec_retry = await _transport_complete_json(
                    transport=transport_outer.outer_transport,
                    model_id=transport_outer.outer_model_id,
                    phase="decompose",
                    payload=reprompt_payload,
                    trace=trace,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    parent_span_id=provider_parent,
                    budget_regime=outer_budget_regime,
                    content_root=cd_content_root,
                    user_id=cd_llm_user_id,
                    channel=cd_llm_channel,
                    workspace_id=cd_llm_workspace_id,
                    executor_tier=cd_llm_executor_tier,
                    workspace=workspace,
                )
                if _decompose_has_usable_steps(dec_retry):
                    dec = dec_retry
                    decompose_recovery = "json_only_reprompt"
                else:
                    wrapped = _wrap_decompose_as_single_step(
                        dec_retry if dec_retry else dec,
                        triage=triage,
                        incoming_text=incoming_text,
                        tool_set=tool_set,
                    )
                    if wrapped is not None:
                        dec = wrapped
                        decompose_recovery = "single_step_wrap"
            d1 = time_ns()
            await _emit(
                trace,
                TraceEvent(
                    kind="cd.decompose",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=parent,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    ts_start_ns=d0,
                    ts_end_ns=d1,
                    status="ok" if _decompose_has_usable_steps(dec) else "error",
                    attrs={"recovery": decompose_recovery} if decompose_recovery else {},
                ),
            )
            if not _decompose_has_usable_steps(dec):
                await _emit(
                    trace,
                    TraceEvent(
                        kind="cd.decompose.error",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=parent,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        tier=str(triage.complexity.value),
                        ts_start_ns=d1,
                        ts_end_ns=d1,
                        status="failed",
                        attrs={"reason": "parse_or_schema"},
                    ),
                )
                end = time_ns()
                await _emit(
                    trace,
                    TraceEvent(
                        kind="cd.turn",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=parent,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        tier=str(triage.complexity.value),
                        ts_start_ns=t0,
                        ts_end_ns=end,
                        status="failed",
                        attrs={"c_d.backend": backend},
                    ),
                )
                snippet_src = (
                    json.dumps(dec, ensure_ascii=False) if isinstance(dec, dict) else str(dec)
                )
                snippet = snippet_src[:200].replace("\n", " ")
                from sevn.prompts.fallbacks import CD_DECOMPOSE_PARSE_FAILURE_PREFIX

                return CdTurnOutcome(
                    status="failed",
                    final_messages=(
                        ChannelPayload(
                            text=f"{CD_DECOMPOSE_PARSE_FAILURE_PREFIX} Snippet: {snippet}",
                        ),
                    ),
                    c_d_backend=backend,
                    rounds_outer_used=0,
                    rounds_inner_exhausted=False,
                    failure_detail="cd.decompose schema/parse failed",
                )
            try:
                plan0 = Plan.model_validate(dec)
            except ValidationError:
                # Steps present but ``summary``/``meta`` malformed: salvage to a
                # single-step plan rather than raise into the gateway error path.
                salvaged = _wrap_decompose_as_single_step(
                    dec,
                    triage=triage,
                    incoming_text=incoming_text,
                    tool_set=tool_set,
                )
                if salvaged is None:
                    raise
                plan0 = Plan.model_validate(salvaged)
            await checkpoint_snapshot(
                trace,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                kind="cd.after_decompose",
                excerpt=f"plan_steps={len(plan0.steps)}",
                state={"plan": plan0.model_dump(mode="json")},
            )
        g0 = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="plan_gate.await",
                span_id=str(uuid.uuid4()),
                parent_span_id=parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                ts_start_ns=g0,
                ts_end_ns=None,
                status="started",
                attrs={},
            ),
        )
        gate = await plan_gate.await_approval(
            plan=plan0,
            session_id=session.session_id,
            turn_id=turn_id,
            trace=trace,
        )
        g1 = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="plan_gate.await",
                span_id=str(uuid.uuid4()),
                parent_span_id=parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                ts_start_ns=g0,
                ts_end_ns=g1,
                status="superseded"
                if gate == "superseded"
                else ("approved" if gate == "approved" else "edited"),
                attrs={},
            ),
        )
        if gate == "superseded":
            end = time_ns()
            await _emit(
                trace,
                TraceEvent(
                    kind="cd.turn",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=parent,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    ts_start_ns=t0,
                    ts_end_ns=end,
                    status="superseded",
                    attrs={"c_d.backend": backend},
                ),
            )
            return CdTurnOutcome(
                status="superseded",
                final_messages=(),
                c_d_backend=backend,
                rounds_outer_used=0,
                rounds_inner_exhausted=False,
            )
        if gate == "approved":
            working = plan0
        else:
            if not isinstance(gate, Plan):
                msg = "PlanGatePort must return 'approved', 'superseded', or a Plan"
                raise TypeError(msg)
            working = gate
        await checkpoint_snapshot(
            trace,
            session_id=session.session_id,
            turn_id=turn_id,
            tier=str(triage.complexity.value),
            kind="cd.after_plan_gate",
            excerpt=str(gate) if isinstance(gate, str) else "plan_edited",
            state={
                "gate": gate if isinstance(gate, str) else gate.model_dump(mode="json"),
                "plan": working.model_dump(mode="json"),
            },
        )

        exec_blob = ""
        if backend == "lambda_rlm":
            allow = _lambda_allowlist_frozen(workspace) & _tool_set_names(tool_set)
            exec_blob, inner_exhausted = await run_lambda_rlm_turn(
                plan=working,
                task=_merge_steer(incoming_text, steer),
                tool_executor=exe,
                tool_ctx=tool_ctx,
                allowlist=allow,
            )
            rounds_outer_used = 1
            await checkpoint_snapshot(
                trace,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                kind="cd.after_lambda_macro",
                excerpt="lambda_macro_complete",
                state={
                    "plan": working.model_dump(mode="json"),
                    "exec_blob": exec_blob,
                },
            )
        else:
            _ = build_rlm_interpreter(workspace)
            sub = transport_outer.sub_lm_transport
            if sub is None:
                msg = "ResolvedCdOuterModels.sub_lm_transport required for dspy C/D RLM phase"
                raise ValueError(msg)
            outer_idx = 0
            partial = ""
            while outer_idx < CD_OUTER_ROUNDS_MAX:
                r0 = time_ns()
                await _emit(
                    trace,
                    TraceEvent(
                        kind="dspy.rlm.outer",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=parent,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        tier=str(triage.complexity.value),
                        ts_start_ns=r0,
                        ts_end_ns=None,
                        status="started",
                        attrs={
                            "outer_index": outer_idx,
                            "inner_llm_calls": inner_llm_total,
                            "max_iterations": CD_RLM_MAX_ITERATIONS,
                            "max_llm_calls": CD_RLM_DEFAULT_MAX_LLM_CALLS,
                            "max_output_chars": CD_RLM_MAX_OUTPUT_CHARS,
                        },
                    ),
                )
                rlm_body = _merge_steer(incoming_text, steer)
                rlm = await _transport_complete_json(
                    transport=sub,
                    model_id=transport_outer.sub_lm_model_id or transport_outer.outer_model_id,
                    phase="rlm_outer",
                    payload={
                        "task": rlm_body,
                        "plan": json.loads(working.model_dump_json()),
                        "outer_index": outer_idx,
                        "max_llm_calls": CD_RLM_DEFAULT_MAX_LLM_CALLS,
                    },
                    trace=trace,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    parent_span_id=provider_parent,
                    budget_regime=sub_budget_regime,
                    content_root=cd_content_root,
                    user_id=cd_llm_user_id,
                    channel=cd_llm_channel,
                    workspace_id=cd_llm_workspace_id,
                    executor_tier=cd_llm_executor_tier,
                    workspace=workspace,
                )
                r1 = time_ns()
                chunk = str(rlm.get("result", ""))
                partial += chunk
                raw_ic = rlm.get("inner_llm_calls", 0)
                inc_calls = int(raw_ic) if isinstance(raw_ic, (int, float)) else 0
                inner_llm_total += inc_calls
                inner_exhausted = bool(rlm.get("inner_exhausted", False))
                await _emit(
                    trace,
                    TraceEvent(
                        kind="dspy.rlm.outer",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=parent,
                        session_id=session.session_id,
                        turn_id=turn_id,
                        tier=str(triage.complexity.value),
                        ts_start_ns=r0,
                        ts_end_ns=r1,
                        status="ok",
                        attrs={
                            "outer_index": outer_idx,
                            "inner_llm_calls": inc_calls,
                        },
                    ),
                )
                rounds_outer_used += 1
                outer_idx += 1
                if not bool(rlm.get("continue_outer", False)):
                    break
            exec_blob = partial
            await checkpoint_snapshot(
                trace,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                kind="cd.after_rlm_outer",
                excerpt=f"outer_rounds={rounds_outer_used}",
                state={
                    "plan": working.model_dump(mode="json"),
                    "outer_rounds": rounds_outer_used,
                    "exec_blob": partial,
                },
            )
        s0 = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="cd.synthesize",
                span_id=str(uuid.uuid4()),
                parent_span_id=parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                ts_start_ns=s0,
                ts_end_ns=None,
                status="started",
                attrs={},
            ),
        )
        syn = await _transport_complete_json(
            transport=transport_outer.outer_transport,
            model_id=transport_outer.outer_model_id,
            phase="synthesize",
            payload={
                "task": _merge_steer(incoming_text, steer),
                "result": _truncate_for_synth(exec_blob),
                "inner_exhausted": inner_exhausted,
                "max_synth_tokens": CD_SYNTH_MAX_TOKENS,
            },
            trace=trace,
            session_id=session.session_id,
            turn_id=turn_id,
            tier=str(triage.complexity.value),
            parent_span_id=provider_parent,
            budget_regime=outer_budget_regime,
            content_root=cd_content_root,
            user_id=cd_llm_user_id,
            channel=cd_llm_channel,
            workspace_id=cd_llm_workspace_id,
            executor_tier=cd_llm_executor_tier,
            workspace=workspace,
        )
        s1 = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="cd.synthesize",
                span_id=str(uuid.uuid4()),
                parent_span_id=parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                ts_start_ns=s0,
                ts_end_ns=s1,
                status="ok",
                attrs={},
            ),
        )
        closing = str(syn.get("final_text", syn.get("text", ""))).strip() or exec_blob.strip()
        if not closing:
            end = time_ns()
            await _emit(
                trace,
                TraceEvent(
                    kind="cd.turn",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=parent,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    tier=str(triage.complexity.value),
                    ts_start_ns=t0,
                    ts_end_ns=end,
                    status="failed",
                    attrs={
                        "c_d.backend": backend,
                        "rounds_outer_used": rounds_outer_used,
                        "rounds_inner_exhausted": inner_exhausted,
                        "reason": "empty_synthesis",
                    },
                ),
            )
            return CdTurnOutcome(
                status="failed",
                final_messages=(),
                c_d_backend=backend,
                rounds_outer_used=rounds_outer_used,
                rounds_inner_exhausted=inner_exhausted,
            )

        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="cd.turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                ts_start_ns=t0,
                ts_end_ns=end,
                status="completed",
                attrs={
                    "c_d.backend": backend,
                    "rounds_outer_used": rounds_outer_used,
                    "rounds_inner_exhausted": inner_exhausted,
                },
            ),
        )
        return CdTurnOutcome(
            status="completed",
            final_messages=(ChannelPayload(text=closing),),
            c_d_backend=backend,
            rounds_outer_used=rounds_outer_used,
            rounds_inner_exhausted=inner_exhausted,
        )
    except BaseException as exc:
        end = time_ns()
        await _emit(
            trace,
            TraceEvent(
                kind="cd.turn",
                span_id=str(uuid.uuid4()),
                parent_span_id=parent,
                session_id=session.session_id,
                turn_id=turn_id,
                tier=str(triage.complexity.value),
                ts_start_ns=t0,
                ts_end_ns=end,
                status="failed",
                attrs={"error": type(exc).__name__, "c_d.backend": backend},
            ),
        )
        if isinstance(exc, Exception):
            return CdTurnOutcome(
                status="failed",
                final_messages=(ChannelPayload(text="Sorry — something went wrong."),),
                c_d_backend=backend,
                rounds_outer_used=rounds_outer_used,
                rounds_inner_exhausted=inner_exhausted,
                failure_detail=str(exc),
            )
        raise


__all__ = [
    "ImmediateApprovedPlanGate",
    "NoOpPlanGate",
    "SupersedingPlanGate",
    "run_cd_turn",
]
