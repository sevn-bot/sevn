"""FastAPI router for signed provider webhooks (`specs/30-non-interactive-triggers.md` §2.2).
Module: sevn.triggers.webhook_router
Depends: fastapi, sevn.triggers.dispatcher
Exports:
    build_webhook_router — include from gateway ``create_app`` **after** ``/webhook/telegram``.
    maybe_import_github_issue_event — inbound issue ingest for ``issues.opened``/``issues.labeled``;
        also schedules auto-run when ``my_sevn.issues.auto_run_on_import`` is enabled.
Each source is an explicit path (e.g. ``/webhook/github``) so generic
``/webhook/{channel}`` gateway routes remain available for bearer-authenticated relays.
"""

from __future__ import annotations

import sqlite3
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S
from sevn.config.workspace_config import WorkspaceConfig
from sevn.runtime.background_tasks import spawn_logged
from sevn.triggers.dedupe import try_insert_webhook_dedupe
from sevn.triggers.dispatcher import (
    TriggerDispatchGate,
    agent_dispatch_kwargs,
    dispatch_notify_only,
    dispatch_run,
)
from sevn.triggers.hooks_protocol import TriggerPluginHookSurface
from sevn.triggers.request import DeliveryMode, DispatchRequest, ResultChannel, RoutingMode
from sevn.triggers.sources.github import (
    GithubWebhookPayload,
    compose_github_prompt,
    verify_github_payload,
)
from sevn.triggers.webhook_secret import resolve_webhook_signing_secret
from sevn.workspace.layout import WorkspaceLayout


async def maybe_import_github_issue_event(
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    *,
    event: str,
    payload: dict[str, object],
    conn: sqlite3.Connection | None = None,
    fanout: object | None = None,
) -> None:
    """Import a GitHub ``issues`` webhook event into the local evolution registry.

    No-op unless ``my_sevn.issues.webhook_import`` is on, the event is
    ``issues.opened``/``issues.labeled``, and the repository matches ``my_sevn.repo_url``.
    Best-effort: failures are logged, not raised, so the webhook still returns 202.

    When ``conn`` is provided and ``my_sevn.issues.auto_run_on_import`` is ``true``,
    schedules ``run_pipeline`` in the background for newly-created issues (``created=True``
    from ``issues.opened`` actions only, per D2).

    Args:
        ws (WorkspaceConfig): Workspace config (repo binding + ingest flags).
        layout (WorkspaceLayout): Workspace layout for the local issue store.
        event (str): ``X-GitHub-Event`` header value (e.g. ``issues``).
        payload (dict[str, object]): Parsed GitHub webhook body.
        conn (sqlite3.Connection | None, optional): SQLite connection for auto-run scheduling.
        fanout (object | None, optional): Evolution event fanout for auto-run pipeline.

    Returns:
        None: Side-effect only (upsert into the local registry; optional auto-run scheduling).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(maybe_import_github_issue_event)
        True
    """
    from sevn.config.my_sevn import effective_my_sevn_issues
    from sevn.evolution.github_sync import import_github_issue_with_created
    from sevn.evolution.issues import my_sevn_repo_slug
    from sevn.integrations.github_skill import resolve_github_skill_hooks

    if event != "issues":
        return
    action = str(payload.get("action") or "")
    if action not in ("opened", "labeled"):
        return
    if not effective_my_sevn_issues(ws).webhook_import:
        return
    repository = payload.get("repository")
    full_name = ""
    if isinstance(repository, dict):
        full_name = str(repository.get("full_name") or "")
    if full_name and full_name.lower() != my_sevn_repo_slug(ws).lower():
        return
    issue_obj = payload.get("issue")
    if not isinstance(issue_obj, dict) or issue_obj.get("number") is None:
        return
    number = int(issue_obj["number"])
    hooks = resolve_github_skill_hooks(ws)
    if hooks.integration_call is None:
        return
    try:
        issue, created = await import_github_issue_with_created(
            layout,
            hooks,
            repo=my_sevn_repo_slug(ws),
            number=number,
            ws=ws,
        )
    except Exception:
        logger.exception("github issue webhook import failed number={}", number)
        return
    if conn is not None and action == "opened":
        from sevn.evolution.pipeline_autostart import maybe_auto_run_pipeline_after_import

        maybe_auto_run_pipeline_after_import(
            layout,
            ws,
            conn,
            issue,
            created=created,
            fanout=fanout,  # type: ignore[arg-type]
        )


async def _dispatch_signed_webhook(*, source: str, request: Request) -> JSONResponse:
    """Verify, dedupe, and enqueue a signed webhook dispatch (GitHub v1).
    Args:
        source (str): Provider key (``github`` only today).
        request (Request): Starlette request with body + headers.
    Returns:
        JSONResponse: **202** with ``correlation_id`` or dedupe duplicate marker.
    Examples:
        >>> import inspect
        >>> from sevn.triggers.webhook_router import _dispatch_signed_webhook
        >>> inspect.iscoroutinefunction(_dispatch_signed_webhook)
        True
    """
    ws: WorkspaceConfig = request.app.state.workspace
    trace: TraceSink = request.app.state.gateway_trace
    if ws.triggers and ws.triggers.paused:
        return JSONResponse(status_code=503, content={"error": "triggers_paused"})
    raw = await request.body()
    lower_headers = {k.lower(): v for k, v in request.headers.items()}
    conn: sqlite3.Connection = request.app.state.sqlite_conn
    layout: WorkspaceLayout = request.app.state.layout
    gate: TriggerDispatchGate = request.app.state.trigger_dispatch_gate
    hooks: TriggerPluginHookSurface | None = getattr(
        request.app.state,
        "trigger_plugin_hooks",
        None,
    )
    try:
        secret = await resolve_webhook_signing_secret(
            ws, source=source, content_root=layout.content_root
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail={"error": "webhook_secret_unresolved"}) from exc
    if source == "github":
        if not verify_github_payload(lower_headers, raw, secret=secret):
            ts = time.time_ns()
            await trace.emit(
                TraceEvent(
                    kind="trigger.signature_invalid",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=None,
                    session_id="trigger",
                    turn_id="webhook",
                    tier=None,
                    ts_start_ns=ts,
                    ts_end_ns=ts,
                    status="fail",
                    attrs={"source": source},
                ),
            )
            raise HTTPException(status_code=401)
        try:
            payload = GithubWebhookPayload.model_validate_json(raw.decode("utf-8"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error": "validation_failed"}) from exc
        delivery_id = lower_headers.get("x-github-delivery")
        if not delivery_id:
            raise HTTPException(status_code=422, detail={"error": "missing_delivery_id"})
        prompt = compose_github_prompt(payload)
        github_event = lower_headers.get("x-github-event", "")
        try:
            body_preview: dict[str, object] = dict(payload.model_dump(mode="python"))
        except Exception:
            body_preview = {}
    else:
        raise HTTPException(status_code=501, detail={"error": "webhook_source_not_implemented"})
    correlation_id = str(uuid.uuid4())
    trigger_meta: dict[str, object] = {
        "transport": "webhook",
        "source": f"webhook:{source}",
        "delivery_id": delivery_id,
    }
    if hooks is not None:
        await hooks.trigger_before_receive(
            transport="webhook",
            correlation_id=correlation_id,
            trigger_meta=dict(trigger_meta),
        )
    ttl = (
        int(ws.triggers.webhook_dedupe_ttl_s)
        if ws.triggers
        else int(
            DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S,
        )
    )
    dedupe = try_insert_webhook_dedupe(
        conn,
        source=source,
        delivery_id=str(delivery_id),
        correlation_id=correlation_id,
        ttl_s=ttl,
    )
    if dedupe == "duplicate":
        ts = time.time_ns()
        await trace.emit(
            TraceEvent(
                kind="trigger.receive",
                span_id=str(uuid.uuid4()),
                parent_span_id=None,
                session_id="trigger",
                turn_id=correlation_id,
                tier=None,
                ts_start_ns=ts,
                ts_end_ns=ts,
                status="duplicate",
                attrs={
                    "correlation_id": correlation_id,
                    "dedupe_duplicate": True,
                    "transport": "webhook",
                },
            ),
        )
        return JSONResponse(
            status_code=202,
            content={"correlation_id": correlation_id, "dedupe": "duplicate"},
        )
    if source == "github":
        fanout = getattr(request.app.state, "evolution_issue_event_fanout", None)
        await maybe_import_github_issue_event(
            ws,
            layout,
            event=github_event,
            payload=body_preview,
            conn=conn,
            fanout=fanout,
        )
    src_cfg: dict[str, object] = {}
    if ws.triggers and ws.triggers.sources and isinstance(ws.triggers.sources.get(source), dict):
        src_cfg = ws.triggers.sources[source]
    delivery_mode_s = str(src_cfg.get("delivery_mode", "agent_pass"))
    delivery_mode: DeliveryMode = (
        "notify_only" if delivery_mode_s == "notify_only" else "agent_pass"
    )
    tmpl = str(src_cfg.get("payload_template") or src_cfg.get("prompt_template") or "{{ prompt }}")
    auto_route = bool(src_cfg.get("auto_route", False))
    routing_mode: RoutingMode = "auto_route" if auto_route else "fixed"
    disp_req = DispatchRequest(
        prompt=prompt,
        routing_mode=routing_mode,
        delivery_mode=delivery_mode,
        permission_template_ref=str(src_cfg.get("permission_template_ref") or "default"),
        allow_tier_cd=bool(src_cfg.get("allow_tier_cd", False)),
        result_channel=ResultChannel(kind="LOG"),
        correlation_id=correlation_id,
        payload=body_preview,
        trigger_meta=trigger_meta,
        notify_template=tmpl if delivery_mode == "notify_only" else None,
    )

    async def background() -> None:
        await gate.acquire_background()
        try:
            if disp_req.delivery_mode == "notify_only":
                await dispatch_notify_only(
                    disp_req,
                    workspace=ws,
                    content_root=layout.content_root,
                    trace=trace,
                    hooks=hooks,
                    invoke_receive_hooks=False,
                )
            else:
                await dispatch_run(
                    disp_req,
                    workspace=ws,
                    content_root=layout.content_root,
                    trace=trace,
                    hooks=hooks,
                    invoke_receive_hooks=False,
                    **agent_dispatch_kwargs(getattr(request.app.state, "gateway_router", None)),
                )
        except Exception:
            logger.exception("webhook_dispatch_failed correlation_id={}", correlation_id)
        finally:
            gate.release_background()

    spawn_logged(background(), label="webhook_dispatch")
    return JSONResponse(status_code=202, content={"correlation_id": correlation_id})


def build_webhook_router() -> APIRouter:
    """Return router with explicit ``/webhook/<provider>`` paths only.
    Returns:
        APIRouter: GitHub handler plus **501** stubs for unimplemented providers.
    Examples:
        >>> from sevn.triggers.webhook_router import build_webhook_router
        >>> r = build_webhook_router()
        >>> any(getattr(rt, "path", "") == "/webhook/github" for rt in r.routes)
        True
    """
    router = APIRouter(tags=["triggers-webhook"])

    @router.post("/webhook/github")
    async def webhook_github(request: Request) -> JSONResponse:
        return await _dispatch_signed_webhook(source="github", request=request)

    @router.post("/webhook/slack")
    async def webhook_slack_stub() -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={
                "deferred": True,
                "spec": "specs/30-non-interactive-triggers.md",
                "source": "slack",
            },
        )

    @router.post("/webhook/stripe")
    async def webhook_stripe_stub() -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={
                "deferred": True,
                "spec": "specs/30-non-interactive-triggers.md",
                "source": "stripe",
            },
        )

    return router
