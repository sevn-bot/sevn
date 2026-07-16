"""Core trigger dispatch (`specs/30-non-interactive-triggers.md` §2.1).

Module: sevn.triggers.dispatcher
Depends: asyncio, jinja2, time, uuid, sevn.agent.tracing

Exports:
    TriggerDispatchGate — concurrency gate for API vs background webhook work.
    agent_dispatch_kwargs — build ``run_turn`` kwargs from gateway router.
    dispatch_notify_only — template render + LOG channel + traces.
    dispatch_run — agent-pass via shared ``RunTurnFn`` when wired at gateway boot.
    notify_issue_watch_diff — operator notify for GitHub issue-watch diffs (D13).
"""

from __future__ import annotations

import asyncio
import html
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import jinja2
from fastapi import HTTPException
from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S
from sevn.config.workspace_config import WorkspaceConfig
from sevn.triggers.delivery import write_log_result
from sevn.triggers.hooks_protocol import TriggerPluginHookSurface
from sevn.triggers.inbox import maybe_spill_prompt_to_inbox
from sevn.triggers.request import DispatchRequest, NotifyHandle, RunHandle
from sevn.triggers.settings import effective_max_inline_bytes

RunTurnFn = Callable[[str, str], Awaitable[None]]

# Built-in cron job id for GitHub issue watch is ISSUE_WATCH_CRON_JOB_ID in
# :mod:`sevn.triggers.issue_watch_cron` (single SSOT).


def notify_issue_watch_diff(
    *,
    diffs: list[dict[str, Any]],
    content_root: Path | None = None,
) -> None:
    """Notify the operator of GitHub issue-watch diffs via operator notify.

    Delivers through the gateway-wired :func:`~sevn.triggers.operator_notify.
    deliver_operator_notify` sink (Telegram to the owner when bootstrapped).
    When unwired, persists a LOG artefact under ``content_root`` instead of
    returning a fake success.

    Args:
        diffs (list[dict[str, Any]]): Diff payloads from ``issue_watch`` /
            ``run_issue_watch_cron`` (each typically has ``repo``, ``number``,
            ``changes``).
        content_root (Path | None, optional): Workspace root for LOG fallback.

    Examples:
        >>> notify_issue_watch_diff(diffs=[])  # no-op
    """
    if not diffs:
        return
    lines: list[str] = ["GitHub issue watch detected changes:"]
    for item in diffs:
        repo = item.get("repo") or "?"
        number = item.get("number") or "?"
        changes = item.get("changes") if isinstance(item.get("changes"), dict) else item
        lines.append(f"- {repo}#{number}: {json.dumps(changes, sort_keys=True)}")
    from sevn.triggers.operator_notify import deliver_operator_notify

    deliver_operator_notify(text="\n".join(lines), content_root=content_root)


def agent_dispatch_kwargs(gateway_router: Any | None) -> dict[str, Any]:
    """Build optional ``dispatch_run`` kwargs from a wired :class:`ChannelRouter`.

    Args:
        gateway_router (Any | None): Gateway router from ``app.state`` (may be ``None``).

    Returns:
        dict[str, Any]: ``run_turn`` and ``session_manager`` when configured.

    Examples:
        >>> agent_dispatch_kwargs(None)
        {}
    """
    if gateway_router is None:
        return {}
    run_turn = getattr(gateway_router, "_run_turn", None)
    if run_turn is None:
        return {}
    return {
        "run_turn": run_turn,
        "session_manager": gateway_router.session_manager,
    }


class TriggerDispatchGate:
    """Bound semaphore for trigger concurrency (`specs/30-non-interactive-triggers.md` §4.3)."""

    def __init__(self, limit: int) -> None:
        """Create a gate allowing up to ``limit`` concurrent trigger dispatches.

        Args:
            limit (int): Semaphore capacity (``effective_max_concurrent``).

        Examples:
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> TriggerDispatchGate(2).limit
            2
        """
        self._limit = int(limit)
        self._sem = asyncio.Semaphore(self._limit)
        self._background_inflight = 0
        self._background_idle = asyncio.Event()
        self._background_idle.set()

    @property
    def limit(self) -> int:
        """Configured capacity (matches constructor ``limit``).

        Returns:
            int: Maximum concurrent in-flight trigger tasks.

        Examples:
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> TriggerDispatchGate(5).limit
            5
        """
        return self._limit

    async def acquire_api_slot(self) -> None:
        """Acquire-or-``429`` when no capacity is immediately available.

        Examples:
            >>> import asyncio
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> async def main():
            ...     g = TriggerDispatchGate(1)
            ...     await g.acquire_api_slot()
            ...     g.release_api_slot()
            >>> asyncio.run(main())
        """
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=0.02)
        except TimeoutError as exc:
            raise HTTPException(
                status_code=429,
                detail={"error": "trigger_concurrency_saturated"},
                headers={"Retry-After": "5"},
            ) from exc

    def release_api_slot(self) -> None:
        """Release one slot after synchronous API handling finishes.

        Examples:
            >>> import asyncio
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> async def main():
            ...     g = TriggerDispatchGate(1)
            ...     await g.acquire_api_slot()
            ...     g.release_api_slot()
            >>> asyncio.run(main())
        """
        self._sem.release()

    async def acquire_background(self) -> None:
        """Block until a background webhook/cron task may start.

        Examples:
            >>> import asyncio
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> async def main():
            ...     g = TriggerDispatchGate(1)
            ...     await g.acquire_background()
            ...     g.release_background()
            >>> asyncio.run(main())
        """
        if self._background_inflight == 0:
            self._background_idle.clear()
        self._background_inflight += 1
        await self._sem.acquire()

    def release_background(self) -> None:
        """Release a background slot acquired via :meth:`acquire_background`.

        Examples:
            >>> import asyncio
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> async def main():
            ...     g = TriggerDispatchGate(1)
            ...     await g.acquire_background()
            ...     g.release_background()
            >>> asyncio.run(main())
        """
        self._sem.release()
        self._background_inflight = max(0, self._background_inflight - 1)
        if self._background_inflight == 0:
            self._background_idle.set()

    async def drain_background(self, *, timeout_s: float = 30.0) -> None:
        """Wait until no background webhook/cron dispatch holds a gate slot.

        Gateway shutdown calls this before closing SQLite so in-flight
        ``asyncio.create_task`` dispatches cannot race ``conn.close()``.

        Args:
            timeout_s (float): Maximum seconds to wait before logging and returning.

        Examples:
            >>> import asyncio
            >>> from sevn.triggers.dispatcher import TriggerDispatchGate
            >>> async def main():
            ...     g = TriggerDispatchGate(1)
            ...     await g.drain_background(timeout_s=0.1)
            >>> asyncio.run(main())
        """
        if self._background_inflight == 0:
            return
        try:
            async with asyncio.timeout(timeout_s):
                await self._background_idle.wait()
        except TimeoutError:
            logger.warning(
                "trigger background drain timed out after {:.1f}s (inflight={})",
                timeout_s,
                self._background_inflight,
            )


async def dispatch_notify_only(
    req: DispatchRequest,
    *,
    workspace: WorkspaceConfig,
    content_root: Path,
    trace: TraceSink,
    hooks: TriggerPluginHookSurface | None = None,
    invoke_receive_hooks: bool = True,
) -> NotifyHandle:
    """Render template, emit traces, write ``LOG`` outcome — never executor/LLM.

    Args:
        req (DispatchRequest): Dispatch envelope (``notify_template`` may be ``None``).
        workspace (WorkspaceConfig): Parsed ``sevn.json`` (permission context; unused v1).
        content_root (Path): Where ``LOG`` artefacts land under ``.sevn``.
        trace (TraceSink): Active gateway trace sink.
        hooks (TriggerPluginHookSurface | None): Optional plugin-hook protocol stub.
        invoke_receive_hooks (bool): When ``False``, skip ``trigger_before_receive``.

    Returns:
        NotifyHandle: Correlation id bookkeeping for the completed notify path.

    Examples:
        >>> import inspect
        >>> from sevn.triggers.dispatcher import dispatch_notify_only
        >>> inspect.iscoroutinefunction(dispatch_notify_only)
        True
    """
    if invoke_receive_hooks and hooks is not None:
        await hooks.trigger_before_receive(
            transport=str(req.trigger_meta.get("transport", "unknown")),
            correlation_id=req.correlation_id,
            trigger_meta=dict(req.trigger_meta),
        )

    receive_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.receive",
            span_id=receive_id,
            parent_span_id=None,
            session_id="trigger",
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=None,
            status="accepted",
            attrs={
                "correlation_id": req.correlation_id,
                "transport": req.trigger_meta.get("transport", "unknown"),
                "dedupe_duplicate": False,
                "delivery_mode": req.delivery_mode,
            },
        ),
    )

    tmpl_src = req.notify_template or "{{ prompt }}"
    env = jinja2.Environment(autoescape=jinja2.select_autoescape(default=True))
    template = env.from_string(tmpl_src)
    rendered = template.render(
        prompt=req.prompt,
        payload=req.payload or {},
        trigger_meta=req.trigger_meta,
    )
    redacted = html.escape(rendered, quote=False)

    notify_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.notify_only",
            span_id=notify_id,
            parent_span_id=receive_id,
            session_id="trigger",
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=None,
            status="rendered",
            attrs={
                "correlation_id": req.correlation_id,
                "template_hash": str(hash(tmpl_src)),
                "redactions_applied": bool(redacted != rendered),
                "transport": req.trigger_meta.get("transport", "unknown"),
            },
        ),
    )

    if req.result_channel.kind == "LOG":
        write_log_result(
            content_root=content_root,
            req=req,
            body={"rendered": redacted, "channel": "LOG"},
        )

    res_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.result",
            span_id=res_id,
            parent_span_id=notify_id,
            session_id="trigger",
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=time.time_ns(),
            status="ok",
            attrs={"correlation_id": req.correlation_id, "channel": req.result_channel.kind},
        ),
    )

    if hooks is not None:
        await hooks.trigger_after_dispatch(
            transport=str(req.trigger_meta.get("transport", "unknown")),
            correlation_id=req.correlation_id,
            trigger_meta=dict(req.trigger_meta),
            status="ok",
        )

    return NotifyHandle(correlation_id=req.correlation_id)


def _trigger_channel_identity(req: DispatchRequest) -> tuple[str, str]:
    """Map ``result_channel`` to gateway session ``(channel, user_id)``.

    Args:
        req (DispatchRequest): Trigger dispatch envelope.

    Returns:
        tuple[str, str]: Channel key and user id for ``ensure_session``.

    Examples:
        >>> from sevn.triggers.request import DispatchRequest, ResultChannel
        >>> _trigger_channel_identity(
        ...     DispatchRequest(
        ...         prompt="x",
        ...         result_channel=ResultChannel(kind="LOG"),
        ...         correlation_id="c1",
        ...     ),
        ... )
        ('trigger', 'c1')
    """
    rc = req.result_channel
    if rc.kind == "TELEGRAM_TOPIC":
        return ("telegram", str(rc.telegram_topic_id or req.correlation_id))
    if rc.kind == "BACK_TO_SOURCE":
        return ("trigger", str(rc.back_to_source or req.correlation_id))
    return ("trigger", req.correlation_id)


def _trigger_scope_key(req: DispatchRequest) -> str:
    """Stable scope key for one non-interactive run session.

    Args:
        req (DispatchRequest): Trigger dispatch envelope.

    Returns:
        str: Scope key passed to ``ensure_session``.

    Examples:
        >>> from sevn.triggers.request import DispatchRequest, ResultChannel
        >>> _trigger_scope_key(
        ...     DispatchRequest(
        ...         prompt="x",
        ...         result_channel=ResultChannel(kind="LOG"),
        ...         correlation_id="c1",
        ...         trigger_meta={"transport": "api"},
        ...     ),
        ... )
        'trigger:api:c1'
    """
    transport = str(req.trigger_meta.get("transport", "unknown"))
    return f"trigger:{transport}:{req.correlation_id}"


def _assistant_texts_for_session(conn: Any, session_id: str) -> list[str]:
    """Collect assistant message bodies after agent dispatch completes.

    Args:
        conn (Any): Open SQLite handle (gateway ``sevn.db``).
        session_id (str): Trigger session id.

    Returns:
        list[str]: Assistant-visible text lines in history order.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_assistant_texts_for_session)
        True
    """
    from sevn.gateway.session_manager import latest_messages

    rows = latest_messages(conn, session_id)
    return [
        str(row.get("content") or "")
        for row in rows
        if row.get("role") == "assistant" and row.get("kind") == "message"
    ]


async def _dispatch_run_agent_pass(
    req: DispatchRequest,
    *,
    run_turn: RunTurnFn,
    session_manager: Any,
    trace: TraceSink,
    dispatch_span_id: str,
) -> str:
    """Bootstrap trigger session, invoke shared ``run_turn``, emit agent trace.

    Args:
        req (DispatchRequest): Spill-adjusted dispatch envelope.
        run_turn (RunTurnFn): Production ``build_agent_run_turn`` closure.
        session_manager (Any): Gateway session manager.
        trace (TraceSink): Active trace sink.
        dispatch_span_id (str): Parent ``trigger.dispatch`` span id.

    Returns:
        str: Trigger session id used for the run.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_dispatch_run_agent_pass)
        True
    """
    channel, user_id = _trigger_channel_identity(req)
    scope_key = _trigger_scope_key(req)
    session_id = await session_manager.ensure_session(
        scope_key=scope_key,
        channel=channel,
        user_id=user_id,
    )
    meta = {
        "trigger_correlation_id": req.correlation_id,
        "trigger_transport": req.trigger_meta.get("transport"),
        "routing_mode": req.routing_mode,
    }
    await session_manager.add_message(
        session_id,
        role="user",
        kind="message",
        content=req.prompt,
        visible_to_llm=1,
        status="sent",
        turn_id=req.correlation_id,
        metadata_blob=json.dumps(meta),
    )
    agent_span_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.agent_dispatch",
            span_id=agent_span_id,
            parent_span_id=dispatch_span_id,
            session_id=session_id,
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=None,
            status="started",
            attrs={
                "correlation_id": req.correlation_id,
                "transport": req.trigger_meta.get("transport", "unknown"),
                "routing_mode": req.routing_mode,
                "session_id": session_id,
            },
        ),
    )
    status = "completed"
    try:
        await run_turn(session_id, req.correlation_id)
    except Exception:
        status = "error"
        raise
    finally:
        await trace.emit(
            TraceEvent(
                kind="trigger.agent_dispatch",
                span_id=str(uuid.uuid4()),
                parent_span_id=agent_span_id,
                session_id=session_id,
                turn_id=req.correlation_id,
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status=status,
                attrs={"correlation_id": req.correlation_id, "session_id": session_id},
            ),
        )
    return str(session_id)


async def dispatch_run(
    req: DispatchRequest,
    *,
    workspace: WorkspaceConfig,
    content_root: Path,
    trace: TraceSink,
    hooks: TriggerPluginHookSurface | None = None,
    invoke_receive_hooks: bool = True,
    dedupe_ttl_s: int = DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S,
    run_turn: RunTurnFn | None = None,
    session_manager: Any | None = None,
) -> RunHandle:
    """Agent-pass entrypoint: shared gateway ``run_turn`` when wired at boot.

    When ``run_turn`` and ``session_manager`` are omitted (unit tests), emits
    ``trigger.agent_skipped`` and writes a LOG stub — production ``create_app``
    always passes the ``build_agent_run_turn`` closure.

    Args:
        req (DispatchRequest): Dispatch envelope after inbox spill rules apply.
        workspace (WorkspaceConfig): Parsed workspace (unused beyond spill policy v1).
        content_root (Path): Spill + ``LOG`` output root.
        trace (TraceSink): Gateway trace sink.
        hooks (TriggerPluginHookSurface | None): Optional plugin-hook stub.
        invoke_receive_hooks (bool): When ``False``, skip ``trigger_before_receive``.
        dedupe_ttl_s (int): Reserved for future dedupe replay windows (ignored v1).
        run_turn (RunTurnFn | None): Production agent dispatch closure.
        session_manager (Any | None): Gateway session manager.

    Returns:
        RunHandle: Run id that mirrors ``correlation_id`` until Mission Control maps ids.

    Examples:
        >>> import inspect
        >>> from sevn.triggers.dispatcher import dispatch_run
        >>> inspect.iscoroutinefunction(dispatch_run)
        True
    """
    _ = dedupe_ttl_s
    max_inline = effective_max_inline_bytes(workspace)
    req = req.model_copy(
        update={
            "prompt": maybe_spill_prompt_to_inbox(
                content_root=content_root,
                correlation_id=req.correlation_id,
                prompt=req.prompt,
                max_inline_bytes=max_inline,
            )
        },
    )

    if invoke_receive_hooks and hooks is not None:
        await hooks.trigger_before_receive(
            transport=str(req.trigger_meta.get("transport", "unknown")),
            correlation_id=req.correlation_id,
            trigger_meta=dict(req.trigger_meta),
        )

    receive_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.receive",
            span_id=receive_id,
            parent_span_id=None,
            session_id="trigger",
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=None,
            status="accepted",
            attrs={
                "correlation_id": req.correlation_id,
                "transport": req.trigger_meta.get("transport", "unknown"),
                "delivery_mode": req.delivery_mode,
                "routing_mode": req.routing_mode,
            },
        ),
    )

    dispatch_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.dispatch",
            span_id=dispatch_id,
            parent_span_id=receive_id,
            session_id="trigger",
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=None,
            status="accepted",
            attrs={
                "correlation_id": req.correlation_id,
                "transport": req.trigger_meta.get("transport", "unknown"),
                "mode": req.delivery_mode,
                "template": req.permission_template_ref,
                "ran_triager": req.routing_mode == "auto_route",
            },
        ),
    )

    exec_id = str(uuid.uuid4())
    agent_status = "stub"
    log_body: dict[str, object] = {"status": "stub", "executor": "unwired"}
    session_id: str | None = None

    if run_turn is not None and session_manager is not None:
        try:
            session_id = await _dispatch_run_agent_pass(
                req,
                run_turn=run_turn,
                session_manager=session_manager,
                trace=trace,
                dispatch_span_id=dispatch_id,
            )
            assistant_texts = _assistant_texts_for_session(
                session_manager.connection,
                session_id,
            )
            agent_status = "completed"
            log_body = {
                "status": "completed",
                "session_id": session_id,
                "assistant_messages": assistant_texts,
            }
        except Exception:
            agent_status = "error"
            log_body = {
                "status": "error",
                "session_id": session_id,
            }
    else:
        await trace.emit(
            TraceEvent(
                kind="trigger.agent_skipped",
                span_id=exec_id,
                parent_span_id=dispatch_id,
                session_id="trigger",
                turn_id=req.correlation_id,
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status="unwired",
                attrs={
                    "correlation_id": req.correlation_id,
                    "note": "run_turn_not_wired",
                },
            ),
        )

    if req.result_channel.kind == "LOG":
        write_log_result(
            content_root=content_root,
            req=req,
            body=log_body,
        )

    res_id = str(uuid.uuid4())
    await trace.emit(
        TraceEvent(
            kind="trigger.result",
            span_id=res_id,
            parent_span_id=dispatch_id,
            session_id=session_id or "trigger",
            turn_id=req.correlation_id,
            tier=None,
            ts_start_ns=time.time_ns(),
            ts_end_ns=time.time_ns(),
            status=agent_status,
            attrs={
                "correlation_id": req.correlation_id,
                "channel": req.result_channel.kind,
            },
        ),
    )

    if hooks is not None:
        await hooks.trigger_after_dispatch(
            transport=str(req.trigger_meta.get("transport", "unknown")),
            correlation_id=req.correlation_id,
            trigger_meta=dict(req.trigger_meta),
            status="ok",
        )

    return RunHandle(run_id=req.correlation_id, correlation_id=req.correlation_id)
