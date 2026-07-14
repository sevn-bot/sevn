"""FastAPI gateway surface (`specs/17-gateway.md` §2.1, §4.2).
Module: sevn.gateway.http_server
Depends: SQLite, harness boot sweep, workspace loader
Exports:
    create_app — ASGI factory.
    deferred_json — ``501`` response helper for deferred endpoints.
    DeferredGatewayOnboardingRoute — ``NotImplementedError`` subclass for ``/onboarding/*``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from sevn.agent.executors.plan_gate_store import expire_pending_plans
from sevn.agent.tracing.emit import wrap_trace_sink
from sevn.agent.tracing.redacting_sink import redact_attrs
from sevn.agent.tracing.sink import (
    SYSTEM_TURN_ID,
    NullTraceSink,
    TraceEvent,
    TraceSink,
    trace_sink_scope,
)
from sevn.agent.tracing.sink_factory import (
    build_gateway_trace_sink_async,
    trace_redaction_policy_for,
)
from sevn.agent.tracing.traces_maintenance import (
    purge_trace_events_ttl,
    write_hourly_rollups,
)
from sevn.channels.webchat import (
    WebChatAdapter,
    WebChatConfig,
    webchat_config_from_workspace,
)
from sevn.cli.repo_sync import RepoSyncError
from sevn.cli.workspace import sevn_home_dir
from sevn.code_understanding.code_index import generate_code_index
from sevn.code_understanding.graphify_mcp import build_effective_mcp_servers
from sevn.config.defaults import (
    DEFAULT_DISPATCHER_CALLBACKS_TTL_SECONDS,
    DEFAULT_GATEWAY_RATE_LIMIT_CAPACITY,
    DEFAULT_GATEWAY_RATE_LIMIT_REFILL_PER_SECOND,
    DEFAULT_GATEWAY_SHUTDOWN_DRAIN_TIMEOUT_S,
    DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS,
    DEFAULT_TRACE_TTL_DAYS,
    DEFAULT_WEBCHAT_AUTH_TIMEOUT_SECONDS,
)
from sevn.config.loader import load_workspace, resolve_sevn_json_path
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig
from sevn.evolution.cursor_poll_scheduler import CursorPollScheduler
from sevn.evolution.repo_sync_scheduler import (
    MY_SEVN_ISSUES_SYNC_CRON_JOB_ID,
    MY_SEVN_SYNC_CRON_JOB_ID,
    run_scheduled_issues_sync,
    run_scheduled_repo_sync,
)
from sevn.evolution.stats import record_last_sync
from sevn.gateway.admin_secrets import register_admin_secrets_routes
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.auth import (
    JWTClaims,
    login_page_html,
    mint_webchat_jwt,
    refresh_webchat_access_token,
    verify_gateway_bearer,
    verify_login_gateway_token,
    verify_telegram_init_data,
    verify_telegram_secret,
    verify_webchat_jwt,
)
from sevn.gateway.boot import run_harness_boot_sweep, run_workspace_layout_validation
from sevn.gateway.boot_registry import BootContext, run_boot_hooks, run_cron_reconciles
from sevn.gateway.channel_boot import register_enabled_channel_adapters
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.deployment_id import load_or_create_deployment_id
from sevn.gateway.dispatcher_callbacks import prune_dispatcher_callbacks
from sevn.gateway.dispatcher_state import sweep_expired_dispatcher_state
from sevn.gateway.e2e_echo import build_echo_run_turn
from sevn.gateway.evolution_issue_events import EvolutionIssueEventFanout
from sevn.gateway.first_session import maybe_reseed_bootstrap_at_boot
from sevn.gateway.gateway_restart_ack import deliver_pending_gateway_restart_acks
from sevn.gateway.gui_proxy import mount_gui_proxy
from sevn.gateway.media_store import MediaStore
from sevn.gateway.mission_api import create_mission_v1_router
from sevn.gateway.mission_state import (
    MissionControlState,
    create_mission_trace_sink,
    detach_mission_trace_sink,
)
from sevn.gateway.onboarding_mount import mount_gateway_onboarding, resolve_gateway_onboarding_token
from sevn.gateway.openai_compat_api import register_openai_compat_routes
from sevn.gateway.outbound_sweep import sweep_outbound_retries
from sevn.gateway.rate_limit import TokenBucketLimiter
from sevn.gateway.self_improve_job_events import (
    SelfImproveJobEventFanout,
    resolve_owner_telegram_user_id,
)
from sevn.gateway.session_manager import SessionManager
from sevn.gateway.shutdown_cleanup import release_leaked_multiprocessing_semaphores
from sevn.gateway.steer_store import SessionSteerStore, owner_user_ids_from_workspace
from sevn.gateway.telegram_resolve import resolve_telegram_bot_token
from sevn.gateway.web_transport import WebChannelTransport
from sevn.gateway.webapp_qa import (
    consume_webapp_dispatcher_token,
    insert_structured_feedback,
    load_webapp_dispatcher_payload,
    resolve_thumbs_polarity,
    resolve_thumbs_transition,
)
from sevn.gateway.webapp_viewer import (
    load_webapp_viewer_payload,
    viewer_stream_snapshot,
    webapp_share_to_story_enabled,
)
from sevn.logging.retention import sweep_rotated_service_logs
from sevn.logging.setup import maybe_boot_service_logging
from sevn.memory.dreaming.defaults import DREAMING_CRON_JOB_ID
from sevn.memory.dreaming.engine import DreamingEngine
from sevn.plugins.registry import (
    build_trigger_mux,
    collect_plugin_slash_bindings,
    load_plugin_hook_chain,
)
from sevn.second_brain.fetch import SecondBrainFetchError, fetch_url_to_raw
from sevn.second_brain.paths import display_scope_root_relative, resolve_scope_root
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.security.secrets.factory import secrets_chain_from_workspace
from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.facade import enqueue_improve_job
from sevn.self_improve.feedback import (
    insert_feedback_event,
    mirror_structured_feedback_to_events,
)
from sevn.self_improve.jobs.worker import ImproveJobWorker
from sevn.self_improve.types import ImproveJobId, OwnerPrincipal
from sevn.skills.browser_gc import prune_orphan_browser_profiles
from sevn.skills.browser_session import (
    close_all_gateway_browsers,
    close_idle_browser_sessions,
    resolve_idle_close_seconds,
)
from sevn.storage.paths import traces_sqlite_path
from sevn.storage.sqlite import open_sevn_sqlite
from sevn.tools.mcp_stdio_client import discover_mcp_tool_definitions
from sevn.tools.runtime_bindings_factory import build_runtime_tool_bindings
from sevn.tools.spill_gc import prune_orphan_tool_result_dirs
from sevn.triggers.api_router import build_api_router
from sevn.triggers.cron import SqliteCronStore, cron_tick
from sevn.triggers.dedupe import prune_webhook_dedupe_expired
from sevn.triggers.dispatcher import (
    TriggerDispatchGate,
    agent_dispatch_kwargs,
    dispatch_notify_only,
    dispatch_run,
)
from sevn.triggers.inbox import prune_inbox_spill
from sevn.triggers.request import DispatchRequest
from sevn.triggers.settings import effective_max_concurrent
from sevn.triggers.webhook_router import build_webhook_router
from sevn.ui.dashboard import register_dashboard_routes
from sevn.ui.dashboard.services import DashboardAuthService
from sevn.ui.dashboard.services.auth import apply_tunnel_local_open_policy
from sevn.ui.openui.bridge import OpenUIBridge, build_content_security_policy
from sevn.ui.openui.callback import (
    build_openui_dispatch_payload,
    normalize_webchat_openui_callback,
    parse_query_dict,
)
from sevn.ui.openui.models import effective_openui_config
from sevn.ui.openui.store import OpenUIStore
from sevn.ui.openui.tokens import verify_token_status
from sevn.ui.shared import register_shared_ui_routes
from sevn.voice.factory import (
    maybe_preload_local_tts,
    prune_stale_tts_files,
    voice_runtime_settings,
)
from sevn.workspace.layout import WorkspaceLayout
from sevn.workspace.source_copy import sync_source_copy

WEBAPP_STATIC_ROOT: Path = (Path(__file__).resolve().parent.parent / "ui" / "webapp").resolve()
MISSION_CONTROL_SPA_ROOT: Path = (
    Path(__file__).resolve().parent.parent / "ui" / "spa" / "dashboard"
).resolve()
_MISSION_CONTROL_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self' data:; "
    "base-uri 'self'; form-action 'self'"
)
_OAUTH_ACCESS_TOKEN_TYPE = "Bearer"  # nosec B105 — OAuth token type label, not a password.
WEBAPP_TELEGRAM_INITDATA_MAX_AGE_SECONDS = 900  # 15 minutes


def _token_budget_alerts_enabled(ws: Any) -> bool:
    """Whether the cumulative ``token_budget`` alert should fire for this workspace.

    Disabled when the triager (main) provider runs on a subscription plan
    (e.g. a MiniMax Token Plan), where the 5-hour / weekly request windows —
    not cumulative per-token totals — are the limiting resource.

    Args:
        ws (Any): Bound workspace config (``WorkspaceConfig``).

    Returns:
        bool: False when the main provider's ``consumption_type`` is ``subscription``.

    Examples:
        >>> _token_budget_alerts_enabled(object())
        True
    """
    from sevn.config.sections.providers import providers_section_dict, resolve_consumption_type

    providers = getattr(ws, "providers", None)
    block = providers_section_dict(providers)
    triager = ""
    tier_default = block.get("tier_default")
    if isinstance(tier_default, dict):
        raw = tier_default.get("triager")
        triager = raw.strip() if isinstance(raw, str) else ""
    if "/" not in triager:
        return True
    provider_name = triager.split("/", 1)[0]
    return resolve_consumption_type(providers, provider_name) != "subscription"


def _mission_control_mount_path() -> str:
    """HTTP path for Mission Control static SPA (``MISSION_CONTROL_MOUNT_PATH``, default ``/mission``).

    Args:
        None.

    Returns:
        str: Normalised mount path without trailing slash.

    Examples:
        >>> _mission_control_mount_path() == "/mission" or True
        True
    """
    raw = (os.environ.get("MISSION_CONTROL_MOUNT_PATH") or "").strip()
    if not raw:
        return "/mission"
    path = raw if raw.startswith("/") else f"/{raw}"
    return path.rstrip("/") or "/mission"


def _mission_spa_root() -> Path:
    """Resolve the Mission Control SPA static root (``MISSION_CONTROL_SPA_ROOT`` env override).

    Args:
        None.

    Returns:
        Path: Directory containing ``index.html`` and built assets.

    Examples:
        >>> _mission_spa_root().name
        'dashboard'
    """
    override = os.environ.get("MISSION_CONTROL_SPA_ROOT", "").strip()
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_dir():
            return candidate
    return MISSION_CONTROL_SPA_ROOT


_MISSION_SPA_MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _mission_serve_static(dist: Path, asset_path: str) -> Response:
    """Serve Mission Control SPA assets with ``index.html`` fallback for path routes.

    Args:
        dist (Path): SPA root directory.
        asset_path (str): URL path fragment after the mount prefix.

    Returns:
        Response: Asset file or SPA shell for client-side routing.

    Examples:
        >>> dist = _mission_spa_root()
        >>> isinstance(_mission_serve_static(dist, "index.html"), Response)
        True
    """
    rel = asset_path.lstrip("/")
    if not rel:
        rel = "index.html"
    candidate = (dist / rel).resolve()
    try:
        candidate.relative_to(dist.resolve())
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    if candidate.is_file():
        media_type = _MISSION_SPA_MIME_TYPES.get(
            candidate.suffix.lower(),
            "application/octet-stream",
        )
        return FileResponse(candidate, media_type=media_type)
    return FileResponse(
        dist / "index.html",
        media_type="text/html; charset=utf-8",
    )


def _mount_mission_control_spa(app: FastAPI) -> None:
    """Mount the sevn Mission Control vanilla JS SPA under :func:`_mission_control_mount_path`.

    Args:
        app (FastAPI): Gateway application instance.

    Returns:
        None: Path routes with ``index.html`` fallback are registered in-place.

    Examples:
        >>> from fastapi import FastAPI
        >>> _mount_mission_control_spa(FastAPI())
        >>> True
        True
    """
    dist = _mission_spa_root()
    if not dist.is_dir():
        logger.warning("Mission Control SPA dist missing at {} — skip mount", dist)
        return
    mount = _mission_control_mount_path()

    @app.get(mount, include_in_schema=False)
    async def _mission_control_slash_redirect() -> RedirectResponse:
        """Redirect ``/mission`` → ``/mission/`` so the SPA shell loads."""
        return RedirectResponse(url=f"{mount}/", status_code=307)

    @app.get(f"{mount}/", include_in_schema=False)
    async def _mission_control_index() -> Response:
        """Serve Mission Control ``index.html`` at the mount root."""
        return _mission_serve_static(dist, "index.html")

    @app.get(f"{mount}/{{full_path:path}}", include_in_schema=False)
    async def _mission_control_spa_path(full_path: str) -> Response:
        """Serve static assets or fall back to ``index.html`` for deep links."""
        return _mission_serve_static(dist, full_path)

    logger.info("Mission Control SPA mounted at {} from {}", mount, dist)


def _telegram_webhook_secret(workspace: WorkspaceConfig) -> str | None:
    """Return the configured Telegram webhook secret or ``None``.
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
    Returns:
        str | None: First non-empty secret candidate.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_telegram_webhook_secret)
        True
    """
    ch = workspace.channels
    if ch is not None and ch.telegram is not None:
        tg = ch.telegram
        for candidate in (tg.webhook_secret, tg.secret_token, tg.webhook_secret_token):
            if candidate and str(candidate).strip():
                return str(candidate).strip()
    return None


def _effective_process_settings(
    workspace: WorkspaceConfig,
    process: ProcessSettings,
) -> ProcessSettings:
    """Merge workspace proxy origin when ``SEVN_PROXY_URL`` is unset in the process env.

    Daemon plists may only set ``SEVN_HOME``; scanner and agent transports still need
    the egress proxy origin per ``specs/02-config-and-workspace.md`` §2.7.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        process (ProcessSettings): Env-derived process settings.

    Returns:
        ProcessSettings: ``process`` or a copy with ``proxy_url`` filled from workspace.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ps = ProcessSettings()
        >>> out = _effective_process_settings(WorkspaceConfig.minimal(), ps)
        >>> out.proxy_url is not None or ps.proxy_url is None
        True
    """
    if (process.proxy_url or "").strip():
        return process
    from sevn.cli.gateway_client import resolve_proxy_base_url

    origin = resolve_proxy_base_url(workspace=workspace).strip()
    if not origin:
        return process
    return process.model_copy(update={"proxy_url": origin})


async def _log_proxy_boot_health(process: ProcessSettings) -> None:
    """Log when the configured egress proxy is unreachable at gateway boot.

    Args:
        process (ProcessSettings): Process-level settings including ``proxy_url``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_log_proxy_boot_health)
        True
    """
    proxy_url = (process.proxy_url or "").strip()
    if not proxy_url:
        return
    health_url = proxy_url.rstrip("/") + "/healthz"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_url)
    except httpx.HTTPError as exc:
        logger.error(
            "egress proxy unreachable at gateway boot ({}): {} — "
            "run `sevn proxy start` or `sevn gateway start` to bring it up",
            health_url,
            exc,
        )
        return
    if response.status_code >= 400:
        logger.error(
            "egress proxy health check failed at gateway boot: {} returned {} — "
            "see logs/proxy.log under the workspace",
            health_url,
            response.status_code,
        )


def _cached_gateway_token(request: Request) -> str | None:
    """Return the gateway bearer token resolved at boot (``app.state.resolved_gateway_token``).

    Args:
        request (Request): Active ASGI request.

    Returns:
        str | None: Resolved bearer token when boot succeeded.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_cached_gateway_token)
        True
    """
    return getattr(request.app.state, "resolved_gateway_token", None)


def _dispatcher_callbacks_ttl_s(workspace: WorkspaceConfig) -> int:
    """Return the configured TTL for the dispatcher callback dedupe table.
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
    Returns:
        int: TTL in seconds (workspace override or default).
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_dispatcher_callbacks_ttl_s)
        True
    """
    if workspace.gateway and workspace.gateway.dispatcher_callbacks_ttl_s is not None:
        return int(workspace.gateway.dispatcher_callbacks_ttl_s)
    return int(DEFAULT_DISPATCHER_CALLBACKS_TTL_SECONDS)


def _shutdown_timeout_s(workspace: WorkspaceConfig) -> float:
    """Return the per-session drain timeout in seconds.
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
    Returns:
        float: Workspace override or :data:`DEFAULT_GATEWAY_SHUTDOWN_DRAIN_TIMEOUT_S`.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(_shutdown_timeout_s)
        True
    """
    if workspace.gateway and workspace.gateway.shutdown_timeout_s is not None:
        return float(workspace.gateway.shutdown_timeout_s)
    return float(DEFAULT_GATEWAY_SHUTDOWN_DRAIN_TIMEOUT_S)


async def _resolve_webchat_jwt_secret(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
) -> str | None:
    """Resolve the HS256 signing secret for the Web UI JWT.
    Resolution order (`specs/19-channel-webui.md` §2.3, §5):
    1. ``channels.webchat.jwt_secret`` inline value (dev / tests).
    2. ``channels.webchat.jwt_secret_ref`` via secrets backend chain (`specs/06-secrets.md`).
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        content_root (Path): Workspace content root for encrypted-file backends.
    Returns:
        str | None: Resolved secret material or ``None`` when neither field is set.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_webchat_jwt_secret)
        True
    """
    ch = workspace.channels
    wc = ch.webchat if ch is not None else None
    if wc is None:
        return None
    inline = getattr(wc, "jwt_secret", None)
    if isinstance(inline, str) and inline.strip():
        return inline.strip()
    ref = getattr(wc, "jwt_secret_ref", None)
    if not ref or not str(ref).strip() or workspace.secrets_backend is None:
        return None
    chain = secrets_chain_from_workspace(content_root, workspace.secrets_backend)
    resolved = await chain.get(str(ref).strip())
    return resolved if resolved else None


async def _prime_unlock_env_and_warn(workspace: WorkspaceConfig, *, content_root: Path) -> None:
    """Self-unlock the encrypted store from the OS keychain, then warn loudly if still locked.

    Mirrors the proxy's self-prime (`proxy/credentials.py`): when the active unlock var is absent
    from the launchd session (wiped on logout), fetch it from the macOS login Keychain so the
    LaunchAgent self-unlocks without ``launchctl setenv``. If the store is still unreachable and a
    Telegram ``bot_token_ref`` routes through it, log an actionable error instead of silently
    degrading to a tokenless boot.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.
        content_root (Path): Workspace content root (reserved for symmetry / future chain reads).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_prime_unlock_env_and_warn)
        True
    """
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.passphrase_prime import (
        keychain_has_unlock_secret,
        reconcile_unlock_env_with_keychain,
        unlock_env_var_for,
    )

    _ = content_root
    key_source = effective_encrypted_file_key_source(workspace.secrets_backend)
    if await reconcile_unlock_env_with_keychain(key_source=key_source):
        logger.info("secrets_unlock_primed_from_keychain key_source={}", key_source)
        return

    var = unlock_env_var_for(key_source)
    if os.environ.get(var, "").strip():
        return
    ch = workspace.channels
    has_tg_ref = bool(
        ch is not None and ch.telegram is not None and (ch.telegram.bot_token_ref or "").strip()
    )
    if not has_tg_ref:
        return
    if await keychain_has_unlock_secret(key_source=key_source):
        return
    logger.error(
        "secrets_store_locked_no_unlock_key key_source={} var={} — the encrypted store cannot be "
        "opened: {} is absent from the daemon session and not in the macOS Keychain. Telegram and "
        "any store-backed secret will be unavailable. Fix: run `sevn secrets store-passphrase` "
        "(macOS, persists across reboot) or export {} before `sevn gateway start`.",
        key_source,
        var,
        var,
        var,
    )


async def _resolve_webapp_telegram_bot_token(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
) -> str | None:
    """Resolve the Telegram bot token for ``/webapp/telegram`` initData verify (§2.5).
    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        content_root (Path): Workspace content root for encrypted-file backends.
    Returns:
        str | None: Resolved token or ``None``.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_webapp_telegram_bot_token)
        True
    """
    ch = workspace.channels
    wc = ch.webchat if ch is not None else None
    if (
        wc is not None
        and getattr(wc, "telegram_bot_token_ref", None)
        and workspace.secrets_backend is not None
    ):
        chain = secrets_chain_from_workspace(content_root, workspace.secrets_backend)
        got = await chain.get(str(wc.telegram_bot_token_ref).strip())
        if got:
            return got
    return await resolve_telegram_bot_token(workspace, content_root=content_root)


def _origin_allowed(*, origin: str | None, allowed: list[str]) -> bool:
    """Return ``True`` when the ``Origin`` request header passes the allow-list.
    No ``Origin`` (same-origin / non-browser client) is accepted. Empty
    ``allowed`` rejects every cross-origin upgrade. An explicit ``"*"`` entry
    permits any origin (loopback dev only — production keeps the list narrow).
    Args:
        origin (str | None): Inbound ``Origin`` header value.
        allowed (list[str]): Configured allow-list from ``WebChatConfig``.
    Returns:
        bool: Whether the upgrade should be accepted.
    Examples:
        >>> _origin_allowed(origin=None, allowed=[])
        True
        >>> _origin_allowed(origin="https://x", allowed=["https://x"])
        True
        >>> _origin_allowed(origin="https://x", allowed=[])
        False
    """
    if not origin:
        return True
    needle = origin.strip().rstrip("/")
    if not needle:
        return True
    if not allowed:
        return False
    for entry in allowed:
        candidate = entry.strip().rstrip("/")
        if not candidate:
            continue
        if candidate in ("*", needle):
            return True
    return False


async def _emit_webchat_trace(
    trace: TraceSink,
    *,
    kind: str,
    session_id: str = "",
    status: str = "ok",
    attrs: dict[str, object] | None = None,
) -> None:
    """Emit one trace event from a webchat HTTP/WS route (`specs/19-channel-webui.md` §7).
    Args:
        trace (TraceSink): Active trace sink.
        kind (str): Span kind label.
        session_id (str): Optional session id attribute.
        status (str): Span status (``ok`` / ``error`` / ``denied`` …).
        attrs (dict[str, object] | None): Extra attribute bundle.
    Returns:
        None: Side-effect only.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_webchat_trace)
        True
    """
    import time

    now = time.time_ns()
    await trace.emit(
        TraceEvent(
            kind=kind,
            span_id=uuid.uuid4().hex,
            parent_span_id=None,
            session_id=session_id,
            turn_id=SYSTEM_TURN_ID,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs=dict(attrs or {}),
        ),
    )


def _boot_seed_mycode(repo_root: Path) -> None:
    """Generate ``.index/mycode/MYCODE.md`` at boot if it is missing or stale.

    Runs deterministically (no LLM) via :func:`sevn.code_understanding.bootstrap.
    mycode_needs_refresh`.  Intended to be executed in a thread-pool executor so
    that it never blocks the FastAPI lifespan startup.

    Args:
        repo_root (Path): Resolved sevn.bot checkout root.

    Returns:
        None

    Examples:
        >>> _boot_seed_mycode.__name__
        '_boot_seed_mycode'
    """
    try:
        from sevn.code_understanding import generate_mycode_markdown, write_mycode
        from sevn.code_understanding.bootstrap import mycode_needs_refresh
        from sevn.code_understanding.mycode_cache import scan_repo_cached
        from sevn.config.defaults import DEFAULT_MYCODE_OUTPUT_RELATIVE

        if not mycode_needs_refresh(repo_root):
            logger.debug("code_orientation: MYCODE.md is current; skipping boot seed")
            return
        logger.info("code_orientation: seeding MYCODE.md at boot (background)")
        digest = scan_repo_cached(repo_root, [])
        body = generate_mycode_markdown(digest, transport=None)
        output = repo_root / DEFAULT_MYCODE_OUTPUT_RELATIVE
        write_mycode(output, body)
        logger.info("code_orientation: MYCODE.md seeded at {}", output)
    except Exception:
        logger.exception("code_orientation_boot_seed_mycode_failed (non-fatal)")


def _boot_seed_graphify(mirror_root: Path) -> None:
    """Seed the Graphify graph into the ``source_code/`` mirror at boot if stale.

    The agent reads ``source_code/.index/graphify/GRAPH_REPORT.md`` for
    architecture orientation; that path resolves to a physical file in the
    workspace mirror (not the checkout), so the graph is built there directly via
    the standalone ``graphify`` CLI. Runs deterministically (AST-only, no LLM) and
    is meant to execute in a thread-pool executor so it never blocks the FastAPI
    lifespan startup. Degrades to a single actionable log line when the ``graphify``
    CLI is not installed; every failure mode is non-fatal.

    Args:
        mirror_root (Path): Workspace content root that holds ``source_code/``.

    Returns:
        None

    Examples:
        >>> _boot_seed_graphify.__name__
        '_boot_seed_graphify'
    """
    try:
        from sevn.code_understanding.graphify_seed import seed_graphify_mirror

        seed_graphify_mirror(mirror_root)
    except Exception:
        logger.exception("code_orientation_boot_seed_graphify_failed (non-fatal)")


def _boot_provision_host_deps(ws: WorkspaceConfig) -> None:
    """Install operator-selected host deps at gateway (re)start before degraded warnings fire.

    Reads ``provisioning.auto_install`` (gated by ``on_gateway_start``): installs the
    selected-and-missing host tools — the core registry (ripgrep/deno/pango/docker) plus the
    voice-only registry (whisper_cpp/ffmpeg, `build-plan-from-review/waves/
    voice-duplex-tts-menu-log-fixes-wave-plan.md` W2) — so a degraded fallback is provisioned
    away instead of merely warned about. When whisper.cpp ends up present, also
    opportunistically downloads the default GGML model and sets ``SEVN_WHISPER_CPP_MODEL`` for
    this process. Best-effort — a bad config or failed installer degrades to a log line and
    never blocks the lifespan. Invoked fire-and-forget via ``run_in_executor`` since installers
    can take many minutes.

    Args:
        ws (WorkspaceConfig): Parsed workspace config.

    Returns:
        None

    Examples:
        >>> _boot_provision_host_deps.__name__
        '_boot_provision_host_deps'
    """
    try:
        prov = ws.provisioning
        from sevn.voice.host_deps import maybe_resolve_whisper_model_env, provision_voice_deps

        maybe_resolve_whisper_model_env()
        if prov is None or not prov.on_gateway_start or not prov.auto_install:
            return
        from sevn.provisioning import provision_host_deps, summarize_report

        report = provision_host_deps(prov.auto_install)
        voice_report = provision_voice_deps(prov.auto_install)
        summary = summarize_report(report)
        voice_summary = summarize_report(voice_report)
        combined = "; ".join(part for part in (summary, voice_summary) if part)
        if report.changed or voice_report.changed:
            logger.info("host_deps_provisioned {}", combined)
        elif combined:
            logger.debug("host_deps {}", combined)
    except Exception:
        logger.exception("host_deps_boot_step_failed (non-fatal)")


def _boot_warn_pdf_render_degraded() -> None:
    """Emit a WARNING at gateway boot when PDF rendering is silently degraded.

    WeasyPrint (a main dependency) binds its native GLib/pango/cairo libraries at
    import via ``cffi.dlopen``; a fresh checkout that ran only ``uv sync`` imports
    the wheel but fails to load ``libgobject-2.0-0`` & co., leaving the agent with
    only the degraded fpdf2 fallback (or no renderer). The fix command exists in
    ``sevn doctor`` but was opt-in — so a live session (2026-06-04) looped ~20 min
    on a PDF render that could never succeed. Surfacing it at boot makes the
    missing-native-libs state visible without the operator having to run doctor.

    Non-fatal: PDF is one feature; the gateway still boots. This warns, it does
    not block startup. Run via ``asyncio.to_thread`` since the WeasyPrint probe
    loads native libs when present.

    Examples:
        >>> _boot_warn_pdf_render_degraded.__name__
        '_boot_warn_pdf_render_degraded'
    """
    try:
        from sevn.pdf.doctor_check import (
            probe_weasyprint_render,
            weasyprint_native_fix_commands,
        )

        row = probe_weasyprint_render()
        if not row.ok:
            logger.warning(
                "pdf_render_degraded: {} — fix: {}",
                row.detail,
                row.hint or weasyprint_native_fix_commands(),
            )
    except Exception:
        logger.exception("pdf_readiness_boot_step_failed (non-fatal)")


def _trace_retention_ttl_days(workspace: WorkspaceConfig) -> int:
    """Resolve trace TTL from ``tracing.retention_days`` with shipped default.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json`` workspace model.
    Returns:
        int: Retention window in days for ``purge_trace_events_ttl``.
    Examples:
        >>> from sevn.config.workspace_config import TracingConfig, WorkspaceConfig
        >>> _trace_retention_ttl_days(
        ...     WorkspaceConfig.minimal(tracing=TracingConfig(retention_days=7)),
        ... )
        7
        >>> _trace_retention_ttl_days(WorkspaceConfig.minimal()) == DEFAULT_TRACE_TTL_DAYS
        True
    """
    tracing = workspace.tracing
    if tracing is not None and tracing.retention_days is not None:
        return tracing.retention_days
    return DEFAULT_TRACE_TTL_DAYS


async def _emit_gateway_trace(
    trace: TraceSink | None,
    *,
    kind: str,
    status: str = "ok",
    attrs: dict[str, object] | None = None,
) -> None:
    """Emit one gateway lifecycle / readiness trace row when ``trace`` is wired.

    Args:
        trace (TraceSink | None): Gateway trace sink from ``app.state.gateway_trace``.
        kind (str): Span kind (``gateway.boot``, ``gateway.shutdown``, …).
        status (str): Span status label.
        attrs (dict[str, object] | None): Optional attribute bundle.
    Returns:
        None: Side-effect only.
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_emit_gateway_trace)
        True
    """
    if trace is None:
        return
    now = time.time_ns()
    await trace.emit(
        TraceEvent(
            kind=kind,
            span_id=uuid.uuid4().hex,
            parent_span_id=None,
            session_id="",
            turn_id=SYSTEM_TURN_ID,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status=status,
            attrs=dict(attrs or {}),
        ),
    )


_WEBAPP_MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _webapp_serve_static(asset_path: str) -> Response:
    """Serve a static asset from the Phase 3 SPA root (`specs/19-channel-webui.md` §4.4).
    Resolves ``asset_path`` against :data:`WEBAPP_STATIC_ROOT` and returns a
    404 when the path escapes the SPA tree or the file is missing.
    Args:
        asset_path (str): Path fragment from the URL.
    Returns:
        Response: ``FileResponse`` on hit or a 404 ``JSONResponse``.
    Examples:
        >>> isinstance(_webapp_serve_static("missing.bin"), Response)
        True
    """
    rel = asset_path.lstrip("/")
    if not rel:
        rel = "index.html"
    candidate = (WEBAPP_STATIC_ROOT / rel).resolve()
    try:
        candidate.relative_to(WEBAPP_STATIC_ROOT)
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    if not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "not_found"})
    media_type = _WEBAPP_MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
    return FileResponse(candidate, media_type=media_type)


def deferred_json(spec_ref: str, *, extra: dict[str, Any] | None = None) -> JSONResponse:
    """Return a ``501`` JSON response pointing at the deferred spec.
    Args:
        spec_ref (str): Spec reference path / anchor for the endpoint.
        extra (dict[str, Any] | None): Optional payload merged into the body.
    Returns:
        JSONResponse: ``501`` response with ``{"deferred": true, "spec": ...}`` body.
    Examples:
        >>> resp = deferred_json("specs/17-gateway.md")
        >>> resp.status_code
        501
    """
    body: dict[str, Any] = {"deferred": True, "spec": spec_ref}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=501, content=body)


class DeferredGatewayOnboardingRoute(NotImplementedError):
    """Raised for placeholder ``/onboarding/*`` routes until the gateway bridges the wizard.
    ``specs/22-onboarding.md`` §10.1 — operators use ``sevn onboard --web`` for the local FastAPI
    wizard; the long-lived gateway must not silently pretend onboarding HTTP is live.
    """


def create_app(
    *,
    workspace: WorkspaceConfig | None = None,
    layout: WorkspaceLayout | None = None,
    process_settings: ProcessSettings | None = None,
    sqlite_connection_factory: Callable[[], sqlite3.Connection] | None = None,
) -> FastAPI:
    """Build the HTTP gateway wired to SQLite + harness boot sweep.
    Args:
        workspace (WorkspaceConfig | None): Pre-loaded workspace; loaded from
            ``sevn.json`` on first request when omitted.
        layout (WorkspaceLayout | None): Pre-resolved workspace layout.
        process_settings (ProcessSettings | None): Env-derived process settings.
        sqlite_connection_factory (Callable[[], sqlite3.Connection] | None):
            Override factory for tests (in-memory DB).
    Returns:
        FastAPI: ASGI application with gateway routes registered.
    Examples:
        >>> import inspect
        >>> inspect.isfunction(create_app)
        True
    """
    resolved_process = process_settings or ProcessSettings()
    # Dedicated limiter for POST /login — not shared with message-routing rate (D3).
    login_rate = TokenBucketLimiter(capacity=5.0, refill_per_second=0.2)

    def _bootstrap_config() -> tuple[WorkspaceConfig, WorkspaceLayout]:
        if workspace is not None and layout is not None:
            return workspace, layout
        sevn_json = resolve_sevn_json_path()
        if sevn_json is None:
            msg = (
                "sevn.json not found — pass ``workspace=`` and ``layout=`` to "
                "``create_app``, set ``SEVN_HOME``, or start from a directory "
                "containing ``sevn.json``."
            )
            raise RuntimeError(msg)
        return load_workspace(sevn_json=sevn_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ws, ly = _bootstrap_config()
        await _prime_unlock_env_and_warn(ws, content_root=ly.content_root)
        apply_tunnel_local_open_policy(ws)
        effective_process = _effective_process_settings(ws, resolved_process)
        from sevn.gateway.gateway_token import resolve_gateway_token_ref

        resolved_gateway_token = await resolve_gateway_token_ref(
            ws,
            content_root=ly.content_root,
            process=effective_process,
        )
        resolved_gateway_token = (resolved_gateway_token or "").strip()
        if not resolved_gateway_token:
            configured = ws.gateway is not None and bool((ws.gateway.token or "").strip())
            if configured:
                msg = (
                    "gateway.token is configured but could not be resolved — "
                    "unlock the secrets store or set SEVN_GATEWAY_TOKEN"
                )
            else:
                msg = (
                    "gateway.token is not configured — "
                    "run `sevn gateway set-gateway-token` or set SEVN_GATEWAY_TOKEN"
                )
            raise RuntimeError(msg)
        from sevn.ui.dashboard.dashboard_password import resolve_dashboard_login_password_ref

        resolved_dashboard_login_password = await resolve_dashboard_login_password_ref(
            ws,
            content_root=ly.content_root,
            process=effective_process,
        )
        resolved_dashboard_login_password = (
            resolved_dashboard_login_password or ""
        ).strip() or None
        maybe_boot_service_logging("gateway", ly.logs_dir)
        trace = await build_gateway_trace_sink_async(ws, ly, content_root=ly.content_root)
        trace_is_null = isinstance(trace, NullTraceSink)
        mission_control_state = MissionControlState(
            token_budget_alerts=_token_budget_alerts_enabled(ws),
        )
        mission_trace_sink = create_mission_trace_sink(mission_control_state)
        trace = wrap_trace_sink(trace)
        app.state.mission_control_state = mission_control_state
        app.state.mission_trace_sink = mission_trace_sink
        if trace_is_null:
            logger.warning(
                "tracing.sinks is empty or all sinks were skipped — traces will not "
                "persist; add the bundled defaults to sevn.json: "
                '"tracing": {{"sinks": [{{"type": "sqlite"}}, '
                '{{"type": "jsonl_file", "path": ".sevn/traces/"}}]}}',
            )
            await _emit_gateway_trace(trace, kind="gateway.trace_sink_disabled", status="warn")
        await _emit_gateway_trace(trace, kind="gateway.boot", status="ok")
        conn = (
            open_sevn_sqlite(ly.dot_sevn)
            if sqlite_connection_factory is None
            else sqlite_connection_factory()
        )
        await run_harness_boot_sweep(conn=conn, trace=trace, workspace=ws)
        await asyncio.to_thread(
            lambda: maybe_reseed_bootstrap_at_boot(conn, workspace=ws, layout=ly),
        )
        await run_workspace_layout_validation(layout=ly, trace=trace)
        # Mirror the full sevn.bot checkout into workspace/source_code/ and refresh the
        # generated code index so the agent reads source with normal workspace paths.
        # Both steps are idempotent + no-op when no real repo root is available.
        try:
            from sevn.config.sevn_repo import resolve_sevn_checkout_with_origin

            repo_root, origin = resolve_sevn_checkout_with_origin(ws, content_root=ly.content_root)
            if repo_root is not None and repo_root.is_dir():
                # Record the checkout the editable ``sevn`` install lives in as the canonical
                # my_sevn.repo_path, so the CLI, ``sevn sync``, and later boots all follow the
                # same tree the operator set sevn up from. A ``$HOME`` folder "scan" is a guess
                # that can match an unrelated clone, so it seeds the mirror but is never pinned
                # (that mis-pin previously recorded a stray dev clone as canonical).
                if origin == "editable":
                    from sevn.config.my_sevn import persist_my_sevn_repo_path

                    if persist_my_sevn_repo_path(ly.sevn_json_path, repo_root):
                        logger.info(
                            "pinned my_sevn.repo_path to editable install checkout {}",
                            repo_root,
                        )
                await asyncio.to_thread(sync_source_copy, ly.content_root, repo_root)
                if (repo_root / "src" / "sevn").is_dir():
                    index_path = repo_root / ".index" / "code_index" / "INDEX.md"
                    await asyncio.to_thread(generate_code_index, repo_root, index_path)
                # Seed MYCODE.md in a background thread so the agent always finds it
                # and is never baited into running the mycode scan skill reactively.
                # The scan itself is pure filesystem (no LLM) so it is safe to run at
                # boot, but we fire-and-forget to avoid blocking the lifespan startup.
                asyncio.get_running_loop().run_in_executor(
                    None,
                    _boot_seed_mycode,
                    repo_root,
                )
                # Seed the Graphify graph into the source_code/ mirror in the
                # background so the agent finds source_code/.index/graphify/
                # GRAPH_REPORT.md instead of looping on "not found" reads. The
                # build shells out to the graphify CLI (AST-only, no LLM) and is
                # non-fatal when the CLI is absent, so it is safe to fire-and-forget.
                asyncio.get_running_loop().run_in_executor(
                    None,
                    _boot_seed_graphify,
                    ly.content_root,
                )
        except Exception:
            logger.exception("source_copy_or_code_index_boot_step_failed (non-fatal)")
        # Log code-orientation status at DEBUG (not WARNING) — the active boot steps
        # above already seed MYCODE.md when missing, so WARNING here only baits the
        # agent into triggering the mycode scan skill again (confirmed in LOG_FINDINGS §3).
        try:
            from sevn.code_understanding.bootstrap import code_orientation_doctor_checks
            from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace

            checkout = resolve_sevn_checkout_for_workspace(ws, content_root=ly.content_root)
            for note in code_orientation_doctor_checks(ws, checkout):
                logger.debug("code_orientation: {}", note)
        except Exception:
            logger.exception("code_orientation_doctor_boot_step_failed (non-fatal)")
        # Provision operator-selected host deps in the background (installers can take minutes).
        # Degraded-fallback warnings below reflect the pre-install state on this boot; a later
        # restart sees the post-install state once provisioning finishes.
        asyncio.get_running_loop().run_in_executor(
            None,
            _boot_provision_host_deps,
            ws,
        )
        await asyncio.to_thread(_boot_warn_pdf_render_degraded)
        vr = voice_runtime_settings(ws)
        await maybe_preload_local_tts(ws)
        await asyncio.to_thread(
            lambda: prune_stale_tts_files(
                content_root=ly.content_root,
                ttl_days=vr.tts_temp_ttl_days,
            ),
        )
        ttl = _dispatcher_callbacks_ttl_s(ws)
        await asyncio.to_thread(lambda: prune_dispatcher_callbacks(conn, ttl_seconds=ttl))
        await asyncio.to_thread(lambda: sweep_expired_dispatcher_state(conn))
        await asyncio.to_thread(lambda: expire_pending_plans(conn))
        # Mission Control trace retention (`specs/04-tracing.md` §10.7 — Option A).
        # Mirrors the snapshot-GC pattern above: boot-time sweep + cron tick.
        traces_db_path = traces_sqlite_path(ly.dot_sevn)
        trace_ttl_days = _trace_retention_ttl_days(ws)
        await asyncio.to_thread(
            purge_trace_events_ttl,
            traces_db_path,
            ttl_days=trace_ttl_days,
        )
        await asyncio.to_thread(
            write_hourly_rollups,
            traces_db_path,
            lookback_hours=DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS,
        )
        await asyncio.to_thread(
            sweep_rotated_service_logs,
            ly.logs_dir,
            content_root=ly.content_root,
            workspace=ws,
        )
        plugin_chain = load_plugin_hook_chain(ws, resolved_process)
        plugin_slash = collect_plugin_slash_bindings(plugin_chain)
        steer_store = SessionSteerStore.from_workspace(ws)
        dispatcher = CommandDispatcher(plugin_slash=plugin_slash, steer_store=steer_store)
        trigger_mux = build_trigger_mux(plugin_chain)
        sessions = SessionManager(conn, content_root=ly.content_root, workspace=ws)
        scanner_ws = ws.model_copy()
        scanner_ws.trace_sink = trace  # type: ignore[attr-defined]
        scanner = LLMGuardScanner(ly.content_root, scanner_ws)
        rate = TokenBucketLimiter(
            capacity=DEFAULT_GATEWAY_RATE_LIMIT_CAPACITY,
            refill_per_second=DEFAULT_GATEWAY_RATE_LIMIT_REFILL_PER_SECOND,
        )
        media = MediaStore(conn, ly.content_root)
        openui_secret = resolved_gateway_token
        openui_store = OpenUIStore(conn)
        await asyncio.to_thread(
            lambda: (openui_store.reap_expired_sqlite(), openui_store.load_from_sqlite())
        )
        openui_bridge = OpenUIBridge(store=openui_store, signing_secret=openui_secret)
        gateway_router = ChannelRouter(
            workspace=ws,
            content_root=ly.content_root,
            sessions=sessions,
            dispatcher=dispatcher,
            scanner=scanner,
            trace=trace,
            rate=rate,
            media=media,
            plugin_hook_chain=plugin_chain,
            owner_user_ids=owner_user_ids_from_workspace(ws),
            steer_store=steer_store,
        )
        from sevn.infrastructure.tunnel_manager import default_manager, tunnel_pid_file

        default_manager.attach_pid_file(tunnel_pid_file(ly.content_root))
        # W3: single RuntimeToolBindings factory (integration W2, sandbox W3, MCP W6).
        _mcp_servers_map = build_effective_mcp_servers(ws, ly.content_root)
        _mcp_tool_defs = await discover_mcp_tool_definitions(_mcp_servers_map)
        _proxy_url = (effective_process.proxy_url if effective_process else None) or None
        _runtime_bindings = build_runtime_tool_bindings(
            ws,
            mcp_servers=_mcp_servers_map,
            proxy_url=_proxy_url,
            session_token=(
                effective_process.session_token if effective_process is not None else None
            ),
        )
        # Persistent deployment id (`specs/17-gateway.md` §10.14 TE-1) — surfaced
        # via ``/status`` and the Logs section in `/config`.
        gateway_router._deployment_id = load_or_create_deployment_id(ly.content_root)
        if os.environ.get("SEVN_E2E_ECHO_TURN", "").strip().lower() in ("1", "true", "yes"):
            gateway_router._run_turn = build_echo_run_turn(gateway_router, conn)
        else:
            gateway_router._run_turn = build_agent_run_turn(
                gateway_router,
                conn,
                ws,
                ly,
                trace,
                process_settings=effective_process,
                runtime_bindings=_runtime_bindings,
                mcp_tool_definitions=_mcp_tool_defs,
            )
        boot_ctx = BootContext(
            app=app,
            workspace=ws,
            layout=ly,
            conn=conn,
            trace=trace,
            gateway_router=gateway_router,
            process_settings=effective_process,
            content_root=ly.content_root,
        )
        artifacts = await register_enabled_channel_adapters(boot_ctx)
        webchat_cfg = (
            artifacts.webchat_config if artifacts is not None else webchat_config_from_workspace(ws)
        )
        web_transport = (
            artifacts.webchat_transport if artifacts is not None else WebChannelTransport()
        )
        webchat_jwt_secret = (
            artifacts.webchat_jwt_secret
            if artifacts is not None
            else await _resolve_webchat_jwt_secret(ws, content_root=ly.content_root)
        )
        await sweep_outbound_retries(conn=conn, router=gateway_router, trace=trace)
        await gateway_router.start_all()
        await deliver_pending_gateway_restart_acks(
            router=gateway_router,
            dot_sevn=ly.dot_sevn,
            deployment_id=gateway_router._deployment_id,
        )
        tele = gateway_router.adapter_named("telegram")
        app.state.sqlite_conn = conn
        app.state.resolved_gateway_token = resolved_gateway_token
        app.state.workspace = ws
        app.state.layout = ly
        app.state.effective_mcp_servers = _mcp_servers_map  # computed above at W6 boot
        app.state.process_settings = effective_process
        app.state.gateway_router = gateway_router
        app.state.gateway_sessions = sessions
        app.state.webchat_config = webchat_cfg
        app.state.webchat_transport = web_transport
        app.state.webchat_jwt_secret = webchat_jwt_secret
        app.state.gateway_trace = trace
        app.state.openui_store = openui_store
        app.state.openui_bridge = openui_bridge
        app.state.openui_secret = openui_secret
        app.state.dashboard_auth_service = DashboardAuthService(
            workspace=ws,
            process_settings=effective_process,
            resolved_login_password=resolved_dashboard_login_password,
            resolved_gateway_token=resolved_gateway_token,
        )
        app.state.trigger_dispatch_gate = TriggerDispatchGate(effective_max_concurrent(ws))
        app.state.trigger_run_status = {}
        app.state.trigger_plugin_hooks = trigger_mux
        app.state.plugin_hook_chain = plugin_chain
        app.state.triggers_cron_store = SqliteCronStore(conn)
        await asyncio.to_thread(run_cron_reconciles, conn, ws)
        app.state.memory_job_lock = asyncio.Lock()
        app.state.dreaming_engine = DreamingEngine(
            conn, trace, app.state.memory_job_lock, transport=None
        )
        app.state.self_improve_job_event_fanout = SelfImproveJobEventFanout(
            hub=getattr(app.state, "dashboard_hub", None),
            telegram=tele,
            workspace=ws,
        )
        app.state.evolution_issue_event_fanout = EvolutionIssueEventFanout(
            hub=getattr(app.state, "dashboard_hub", None),
            telegram=tele,
            workspace=ws,
        )
        evo_handler = getattr(gateway_router, "_evolution_approval_callback_handler", None)
        if evo_handler is not None:
            evo_handler._fanout = app.state.evolution_issue_event_fanout
            evo_handler._owner_user_id = resolve_owner_telegram_user_id(ws)
        evo_cmd = getattr(gateway_router, "_evolution_command_handler", None)
        if evo_cmd is not None:
            evo_cmd._fanout = app.state.evolution_issue_event_fanout

        async def _gateway_enqueue_improve_job(
            *,
            workspace_id: str,
            experiment_id: str,
            trigger: Literal["manual", "cron"],
            correlation_id: str | None,
            owner_principal: OwnerPrincipal,
            client_token: str | None = None,
        ) -> ImproveJobId:
            """Gateway-bound enqueue path with ``app.state.gateway_trace`` wired."""
            return await enqueue_improve_job(
                workspace_id=workspace_id,
                experiment_id=experiment_id,
                trigger=trigger,
                correlation_id=correlation_id,
                owner_principal=owner_principal,
                workspace_config=ws,
                layout=ly,
                sqlite_conn=conn,
                client_token=client_token,
                job_event_fanout=app.state.self_improve_job_event_fanout,
                trace_sink=app.state.gateway_trace,
                improve_job_worker=getattr(app.state, "improve_job_worker", None),
            )

        app.state.enqueue_improve_job = _gateway_enqueue_improve_job
        app.state.self_improve_facade = app.state.self_improve_job_event_fanout
        if os.environ.get("SEVN_E2E_ECHO_TURN", "").strip().lower() not in ("1", "true", "yes"):
            gateway_router._run_turn = build_agent_run_turn(
                gateway_router,
                conn,
                ws,
                ly,
                trace,
                process_settings=effective_process,
                runtime_bindings=_runtime_bindings,
                mcp_tool_definitions=_mcp_tool_defs,
                enqueue_improve_job=_gateway_enqueue_improve_job,
            )
        improve_job_worker: ImproveJobWorker | None = None
        if effective_self_improve_enabled(ws):
            workspace_id = ws.workspace_root or str(ly.content_root)
            improve_job_worker = ImproveJobWorker(
                sqlite_conn=conn,
                workspace_config=ws,
                layout=ly,
                workspace_id=workspace_id,
                job_event_fanout=app.state.self_improve_job_event_fanout,
                trace_sink=trace,
            )
            await improve_job_worker.start()
        app.state.improve_job_worker = improve_job_worker

        # FL-4C.3 — Cursor Cloud background poll scheduler.
        cursor_poll_scheduler = CursorPollScheduler(
            sqlite_conn=conn,
            workspace_config=ws,
            layout=ly,
            fanout=getattr(app.state, "evolution_issue_event_fanout", None),
        )
        await cursor_poll_scheduler.start()
        app.state.cursor_poll_scheduler = cursor_poll_scheduler

        def _boot_prune_dedupe(c: sqlite3.Connection) -> None:
            prune_webhook_dedupe_expired(c)

        await asyncio.to_thread(_boot_prune_dedupe, conn)
        prune_inbox_spill(content_root=ly.content_root)

        async def _dispatch_trigger(req: DispatchRequest) -> None:
            if (
                req.trigger_meta.get("transport") == "cron"
                and req.trigger_meta.get("cron_job_id") == DREAMING_CRON_JOB_ID
            ):
                eng = getattr(app.state, "dreaming_engine", None)
                if eng is not None:
                    st = app.state
                    await eng.run_scheduled(workspace_root=st.layout.content_root, ws=st.workspace)
                return
            if (
                req.trigger_meta.get("transport") == "cron"
                and req.trigger_meta.get("cron_job_id") == MY_SEVN_SYNC_CRON_JOB_ID
            ):
                st = app.state
                proc = getattr(st, "process_settings", None)
                home = proc.home if proc is not None and proc.home is not None else sevn_home_dir()
                try:
                    detail = await asyncio.to_thread(run_scheduled_repo_sync, home=home)
                    await asyncio.to_thread(
                        record_last_sync,
                        st.layout,
                        status="ok",
                        detail=detail,
                    )
                except RepoSyncError as exc:
                    logger.warning("my_sevn repo sync cron failed: {}", exc)
                    await asyncio.to_thread(
                        record_last_sync,
                        st.layout,
                        status="error",
                        detail=str(exc),
                    )
                return
            if (
                req.trigger_meta.get("transport") == "cron"
                and req.trigger_meta.get("cron_job_id") == MY_SEVN_ISSUES_SYNC_CRON_JOB_ID
            ):
                st = app.state
                try:
                    await run_scheduled_issues_sync(st.layout, st.workspace)
                except Exception:
                    logger.exception("my_sevn issues sync cron failed")
                return
            hooks = getattr(app.state, "trigger_plugin_hooks", None)
            if req.delivery_mode == "notify_only":
                await dispatch_notify_only(
                    req,
                    workspace=ws,
                    content_root=ly.content_root,
                    trace=trace,
                    hooks=hooks,
                )
            else:
                await dispatch_run(
                    req,
                    workspace=ws,
                    content_root=ly.content_root,
                    trace=trace,
                    hooks=hooks,
                    **agent_dispatch_kwargs(gateway_router),
                )

        app.state.dispatch_trigger = _dispatch_trigger

        async def _cron_minute_loop(app_ref: FastAPI) -> None:
            while True:
                await asyncio.sleep(60)
                try:
                    st = app_ref.state
                    await cron_tick(
                        cron_store=SqliteCronStore(st.sqlite_conn),
                        workspace=st.workspace,
                        content_root=st.layout.content_root,
                        trace=st.gateway_trace,
                        dispatch=_dispatch_trigger,
                    )
                    conn_ref = st.sqlite_conn
                    layout_root = st.layout.content_root

                    def _prune_dedupe(c: sqlite3.Connection) -> None:
                        prune_webhook_dedupe_expired(c)

                    await asyncio.to_thread(_prune_dedupe, conn_ref)
                    await asyncio.to_thread(sweep_expired_dispatcher_state, conn_ref)
                    prune_inbox_spill(content_root=layout_root)
                    await asyncio.to_thread(
                        prune_orphan_tool_result_dirs,
                        content_root=layout_root,
                        conn=conn_ref,
                    )
                    idle_close_s = resolve_idle_close_seconds(st.workspace)
                    if idle_close_s > 0:
                        await asyncio.to_thread(
                            close_idle_browser_sessions,
                            content_root=layout_root,
                            idle_seconds=idle_close_s,
                        )
                    await asyncio.to_thread(
                        prune_orphan_browser_profiles,
                        content_root=layout_root,
                        conn=conn_ref,
                    )
                    traces_db = traces_sqlite_path(st.layout.dot_sevn)
                    trace_ttl_days = _trace_retention_ttl_days(st.workspace)
                    await asyncio.to_thread(
                        purge_trace_events_ttl,
                        traces_db,
                        ttl_days=trace_ttl_days,
                    )
                    await asyncio.to_thread(
                        write_hourly_rollups,
                        traces_db,
                        lookback_hours=DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS,
                    )
                    await asyncio.to_thread(
                        sweep_rotated_service_logs,
                        st.layout.logs_dir,
                        content_root=st.layout.content_root,
                        workspace=st.workspace,
                    )
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("cron_tick loop failed")

        cron_task = asyncio.create_task(_cron_minute_loop(app))
        app.state.triggers_cron_task = cron_task
        await _log_proxy_boot_health(effective_process)
        await run_boot_hooks(
            BootContext(
                app=app,
                workspace=ws,
                layout=ly,
                conn=conn,
                trace=trace,
                gateway_router=gateway_router,
                process_settings=effective_process,
                content_root=ly.content_root,
            )
        )
        # W3.1/W3.3: the subagents boot hook (priority 40) populates
        # `app.state.subagent_supervisor` above; `agent_turn.py` reads it lazily off
        # the router (`router._subagent_supervisor`) rather than as a
        # `build_agent_run_turn` constructor param, since both call sites of that
        # factory run *before* `run_boot_hooks` above.
        gateway_router._subagent_supervisor = getattr(app.state, "subagent_supervisor", None)
        yield
        await _emit_gateway_trace(trace, kind="gateway.shutdown", status="ok")
        cursor_sched = getattr(app.state, "cursor_poll_scheduler", None)
        if isinstance(cursor_sched, CursorPollScheduler):
            await cursor_sched.stop()
        improve_worker = getattr(app.state, "improve_job_worker", None)
        if isinstance(improve_worker, ImproveJobWorker):
            await improve_worker.stop()
        cron_task.cancel()
        with suppress(asyncio.CancelledError):
            await cron_task
        await gateway_router.stop_all()
        trigger_gate = getattr(app.state, "trigger_dispatch_gate", None)
        if isinstance(trigger_gate, TriggerDispatchGate):
            await trigger_gate.drain_background(timeout_s=_shutdown_timeout_s(ws))
        await sessions.drain(grace_period_s=_shutdown_timeout_s(ws))
        await asyncio.to_thread(
            close_all_gateway_browsers,
            content_root=ly.content_root,
            conn=conn,
        )
        await asyncio.to_thread(
            prune_orphan_tool_result_dirs,
            content_root=ly.content_root,
            conn=conn,
        )
        await asyncio.to_thread(
            prune_orphan_browser_profiles,
            content_root=ly.content_root,
            conn=conn,
        )
        await web_transport.drain()
        op_store = getattr(app.state, "openui_store", None)
        if isinstance(op_store, OpenUIStore):
            await asyncio.to_thread(op_store.flush_to_sqlite)
        mission_sub = getattr(app.state, "mission_trace_sink", None)
        if mission_sub is not None:
            detach_mission_trace_sink(mission_sub)
        await trace.close()
        conn.close()
        with suppress(Exception):
            release_leaked_multiprocessing_semaphores()

    app = FastAPI(title="sevn-gateway", lifespan=lifespan)
    register_shared_ui_routes(app)
    register_dashboard_routes(app, workspace, process_settings=resolved_process)
    mount_gateway_onboarding(app, token=resolve_gateway_onboarding_token())

    @app.middleware("http")
    async def _bind_trace_sink_middleware(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Any:
        sink = getattr(request.app.state, "gateway_trace", None)
        with trace_sink_scope(sink if isinstance(sink, TraceSink) else None):
            return await call_next(request)

    @app.middleware("http")
    async def _mission_control_csp_middleware(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Any:
        """Apply a conservative CSP to vendored Mission Control static responses."""
        response = await call_next(request)
        mount = _mission_control_mount_path()
        path = request.url.path
        if (path == mount or path.startswith(f"{mount}/")) and (
            "content-security-policy" not in {k.lower() for k in response.headers}
        ):
            response.headers["Content-Security-Policy"] = _MISSION_CONTROL_CSP
        return response

    @app.exception_handler(DeferredGatewayOnboardingRoute)
    async def _deferred_onboarding_route_handler(
        _request: Request, exc: DeferredGatewayOnboardingRoute
    ) -> JSONResponse:
        return deferred_json(
            "specs/22-onboarding.md",
            extra={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Readiness: SQLite open + optional proxy ping.
        Failure modes (operators): **503 ``sqlite: false``** when ``sevn.db`` is not
        opened on ``app.state`` or ``SELECT 1`` raises — check disk permissions and
        migration head. **``proxy.ok: false``** when ``ProcessSettings.proxy_url`` is
        set but the proxy ``/health`` probe fails — egress or proxy process down
        (`specs/07-egress-proxy.md`). See inline notes in ``specs/17-gateway.md`` §10.6.
        """
        conn_local: sqlite3.Connection | None = getattr(request.app.state, "sqlite_conn", None)
        trace_local: TraceSink | None = getattr(request.app.state, "gateway_trace", None)
        if conn_local is None:
            await _emit_gateway_trace(
                trace_local,
                kind="gateway.deploy_readiness",
                status="error",
                attrs={"ready": False, "sqlite": False},
            )
            return JSONResponse(status_code=503, content={"ready": False, "sqlite": False})
        try:
            conn_local.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            await _emit_gateway_trace(
                trace_local,
                kind="gateway.deploy_readiness",
                status="error",
                attrs={"ready": False, "sqlite": False},
            )
            return JSONResponse(status_code=503, content={"ready": False, "sqlite": False})
        body: dict[str, Any] = {"ready": True, "sqlite": True}
        proc: ProcessSettings = request.app.state.process_settings
        if proc.proxy_url:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(proc.proxy_url.rstrip("/") + "/healthz")
                body["proxy"] = {"ok": r.status_code < 400}
            except (httpx.HTTPError, OSError, ValueError):
                body["proxy"] = {"ok": False}
        ready_status = "ok" if body.get("ready") else "error"
        await _emit_gateway_trace(
            trace_local,
            kind="gateway.deploy_readiness",
            status=ready_status,
            attrs=body,
        )
        return JSONResponse(body)

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        from sevn.gateway.prometheus_metrics import render_gateway_metrics

        session_mgr = getattr(app.state, "session_manager", None)
        active_sessions = 0
        if session_mgr is not None and hasattr(session_mgr, "active_session_count"):
            active_sessions = int(session_mgr.active_session_count())
        subagents_running: dict[tuple[int, str], int] | None = None
        subagents_total: dict[str, int] | None = None
        prom = getattr(app.state, "subagent_prometheus", None)
        if prom is not None:
            subagents_running = dict(prom.running)
            subagents_total = dict(prom.total_by_status)
        txt = render_gateway_metrics(
            active_sessions=active_sessions,
            subagents_running=subagents_running,
            subagents_total=subagents_total,
        )
        return PlainTextResponse(txt, media_type="text/plain; version=0.0.4")

    async def enforce_gateway_auth(request: Request) -> None:
        token = _cached_gateway_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="unauthorized")
        if verify_gateway_bearer(
            configured=token,
            authorization_header=request.headers.get("Authorization"),
        ):
            return
        raise HTTPException(status_code=401, detail="unauthorized")

    register_admin_secrets_routes(app, enforce_gateway_auth=enforce_gateway_auth)
    mount_gui_proxy(app, resolve_gateway_token=_cached_gateway_token)
    # MC-14: legacy /api/v1/mission/* → HTTP 410 (SPA uses /api/v1/* + /ws/dashboard).
    app.include_router(create_mission_v1_router())

    @app.post("/webhook/telegram")
    async def webhook_telegram(request: Request) -> Response:
        ws_local: WorkspaceConfig = request.app.state.workspace
        secret = _telegram_webhook_secret(ws_local)
        if not verify_telegram_secret(
            configured=secret,
            header_value=request.headers.get("X-Telegram-Bot-Api-Secret-Token"),
        ):
            return Response(status_code=401, content=b"")
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid_json") from exc
        router_local: ChannelRouter = request.app.state.gateway_router
        await router_local.handle_webhook("telegram", body)
        return JSONResponse({"ok": True})

    app.include_router(build_webhook_router())
    app.include_router(build_api_router())
    register_openai_compat_routes(app)

    @app.post("/webhook/{channel}")
    async def webhook_channel(
        channel: str,
        request: Request,
        _ok: None = Depends(enforce_gateway_auth),
    ) -> JSONResponse:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid_json") from exc
        router_local: ChannelRouter = request.app.state.gateway_router
        await router_local.handle_webhook(channel, body)
        return JSONResponse({"ok": True})

    @app.websocket("/ws/webchat")
    async def ws_webchat(websocket: WebSocket) -> None:
        """Owner WebSocket chat per `specs/19-channel-webui.md` §2.2-§2.6.
        Lifecycle:
        1. Verify ``Origin`` against ``channels.webchat.allowed_origins``.
        2. Accept and wait for an ``auth`` frame within
           :data:`DEFAULT_WEBCHAT_AUTH_TIMEOUT_SECONDS`; otherwise close ``4401``.
        3. On success, register the connection in :class:`WebChannelTransport`
           and emit a ``ready`` frame containing the resolved ``session_id``.
        4. Subsequent frames pass through :meth:`WebChatAdapter.ingest_ws_frame`
           and the standard :meth:`ChannelRouter.route_incoming` pipeline.
        """
        trace_local: TraceSink = websocket.app.state.gateway_trace

        async def _session() -> None:
            cfg: WebChatConfig = websocket.app.state.webchat_config
            transport_local: WebChannelTransport = websocket.app.state.webchat_transport
            secret: str | None = websocket.app.state.webchat_jwt_secret
            router_local: ChannelRouter = websocket.app.state.gateway_router
            sessions_local: SessionManager = websocket.app.state.gateway_sessions
            origin = websocket.headers.get("origin")
            if not _origin_allowed(origin=origin, allowed=list(cfg.allowed_origins)):
                await _emit_webchat_trace(
                    trace_local,
                    kind="gateway.webchat.origin_denied",
                    status="denied",
                    attrs={"origin": origin or ""},
                )
                await websocket.close(code=4403)
                return
            await websocket.accept()
            client_id = uuid.uuid4().hex
            await _emit_webchat_trace(
                trace_local,
                kind="gateway.webchat.connect",
                attrs={"client_id": client_id},
            )
            try:
                try:
                    raw = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=DEFAULT_WEBCHAT_AUTH_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    await _emit_webchat_trace(
                        trace_local,
                        kind="gateway.webchat.auth_failed",
                        status="timeout",
                        attrs={"client_id": client_id},
                    )
                    await websocket.close(code=4401)
                    return
                except WebSocketDisconnect:
                    return
                try:
                    first = json.loads(raw)
                except (ValueError, TypeError):
                    await websocket.close(code=4401)
                    return
                if not isinstance(first, dict) or first.get("type") != "auth":
                    await websocket.close(code=4401)
                    return
                token = first.get("token")
                claims: JWTClaims | None = None
                if isinstance(token, str) and token and secret:
                    claims = verify_webchat_jwt(secret=secret, token=token)
                if claims is None and cfg.public and not (isinstance(token, str) and token.strip()):
                    anon_sub = f"anon:{client_id}"
                    claims = JWTClaims(
                        sub=anon_sub,
                        aud="webchat",
                        exp=0,
                        scope=("session:read", "session:write"),
                    )
                if claims is None:
                    await _emit_webchat_trace(
                        trace_local,
                        kind="gateway.webchat.auth_failed",
                        status="invalid",
                        attrs={"client_id": client_id},
                    )
                    await websocket.close(code=4401)
                    return
                scope_key = f"webchat:{claims.sub}"
                session_id = await sessions_local.ensure_session(
                    scope_key=scope_key,
                    channel="webchat",
                    user_id=claims.sub,
                )
                await transport_local.register(
                    session_id=session_id,
                    client_id=client_id,
                    ws=websocket,
                )
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "ready",
                            "session_id": session_id,
                            "client_id": client_id,
                            "user_id": claims.sub,
                            "caps": {
                                "tts_inline": cfg.tts_inline,
                                "public": cfg.public,
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
                adapter = router_local.adapter_named("webchat")
                if not isinstance(adapter, WebChatAdapter):
                    raise RuntimeError("webchat adapter not registered")
                while True:
                    try:
                        raw_frame = await websocket.receive_text()
                    except WebSocketDisconnect:
                        break
                    try:
                        frame = json.loads(raw_frame)
                    except (ValueError, TypeError):
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "code": "invalid_json",
                                    "message": "frame must be UTF-8 JSON",
                                },
                                ensure_ascii=False,
                            ),
                        )
                        continue
                    if not isinstance(frame, dict):
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "code": "invalid_frame",
                                    "message": "frame must be a JSON object",
                                },
                                ensure_ascii=False,
                            ),
                        )
                        continue
                    frame_type = frame.get("type")
                    if frame_type == "ping":
                        nonce = frame.get("nonce")
                        pong: dict[str, Any] = {"type": "pong"}
                        if nonce is not None:
                            pong["nonce"] = nonce
                        await websocket.send_text(json.dumps(pong, ensure_ascii=False))
                        continue
                    if frame_type == "auth":
                        continue
                    if frame_type == "cancel":
                        cancelled = await sessions_local.cancel_active_dispatch(session_id)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "cancelled",
                                    "session_id": session_id,
                                    "ok": cancelled,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        continue
                    if frame_type == "client_meta":
                        # §4 (`PROBLEMS.md`): webchat auto-detect — first
                        # ``client_meta`` frame from the SPA carries the
                        # browser's ``Intl.DateTimeFormat().resolvedOptions()
                        # .timeZone``. Persist when the profile is still on
                        # the UTC default so explicit ``/config`` choices
                        # from another channel aren't clobbered.
                        from sevn.gateway.user_profile import (
                            get_user_profile,
                            set_user_timezone,
                        )

                        client_tz = frame.get("timezone")
                        if isinstance(client_tz, str) and client_tz.strip():
                            existing_profile = await asyncio.to_thread(
                                get_user_profile,
                                sessions_local.connection,
                                channel="webchat",
                                user_id=claims.sub,
                            )
                            if existing_profile.timezone == "UTC":
                                # Bad IANA name → ignore silently; the SPA
                                # will keep its UTC default rendering.
                                with contextlib.suppress(ValueError):
                                    await asyncio.to_thread(
                                        set_user_timezone,
                                        sessions_local.connection,
                                        channel="webchat",
                                        user_id=claims.sub,
                                        timezone=client_tz.strip(),
                                    )
                        continue
                    if frame.get("session_id") not in (None, session_id):
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "code": "session_forbidden",
                                    "message": "session_id does not belong to this connection",
                                },
                                ensure_ascii=False,
                            ),
                        )
                        await _emit_webchat_trace(
                            trace_local,
                            kind="gateway.session_forbidden",
                            session_id=session_id,
                            status="denied",
                            attrs={"client_id": client_id},
                        )
                        continue
                    frame.setdefault("session_id", session_id)
                    incoming = adapter.ingest_ws_frame(
                        frame,
                        claims=claims,
                        client_id=client_id,
                        expected_session_id=session_id,
                    )
                    if incoming is not None:
                        incoming = normalize_webchat_openui_callback(incoming)
                    if incoming is None:
                        if frame_type not in {"message", "callback", "file"}:
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "type": "error",
                                        "code": "unknown_frame",
                                        "message": f"unsupported frame type: {frame_type!r}",
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                        continue
                    try:
                        await router_local.route_incoming(incoming)
                    except Exception:
                        logger.exception("webchat_route_incoming_failed client_id={}", client_id)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "code": "ingest_failed",
                                    "message": "could not process frame",
                                },
                                ensure_ascii=False,
                            ),
                        )
            finally:
                await transport_local.unregister(client_id)
                await _emit_webchat_trace(
                    trace_local,
                    kind="gateway.webchat.disconnect",
                    attrs={"client_id": client_id},
                )

        with trace_sink_scope(trace_local):
            await _session()

    @app.get("/login")
    async def login_get(request: Request) -> HTMLResponse:
        """Operator gateway bearer login shell (`specs/17-gateway.md` §2.1)."""
        required = bool(_cached_gateway_token(request))
        return HTMLResponse(login_page_html(gateway_auth_required=required))

    @app.post("/login")
    async def login_post(request: Request) -> JSONResponse:
        """Validate gateway bearer and allow the SPA to store it client-side."""
        client_key = request.client.host if request.client else "unknown"
        if not await login_rate.allow(f"login:{client_key}"):
            raise HTTPException(status_code=429, detail="rate_limited")
        configured = _cached_gateway_token(request)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        token_raw = payload.get("token") if isinstance(payload, dict) else None
        submitted = token_raw.strip() if isinstance(token_raw, str) else ""
        if not verify_login_gateway_token(configured=configured, submitted=submitted or None):
            raise HTTPException(status_code=401, detail="unauthorized")
        return JSONResponse({"ok": True})

    @app.post("/auth/refresh")
    async def auth_refresh(request: Request) -> JSONResponse:
        """Refresh ``aud=webchat`` JWT (`specs/19-channel-webui.md` §2.3)."""
        cfg: WebChatConfig = request.app.state.webchat_config
        secret: str | None = request.app.state.webchat_jwt_secret
        if not secret:
            raise HTTPException(status_code=503, detail="webchat_jwt_secret_unconfigured")
        refreshed = refresh_webchat_access_token(
            secret=secret,
            ttl_seconds=int(cfg.jwt_ttl_seconds),
            authorization_header=request.headers.get("Authorization"),
            gateway_configured=_cached_gateway_token(request),
        )
        if refreshed is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        token, expires_in, _sub = refreshed
        return JSONResponse(
            {
                "access_token": token,
                "token_type": _OAUTH_ACCESS_TOKEN_TYPE,
                "expires_in": expires_in,
            },
        )

    @app.get("/api/webchat/config")
    async def webchat_public_config(request: Request) -> JSONResponse:
        """Expose non-secret webchat flags for the static SPA (`specs/19-channel-webui.md`)."""
        cfg: WebChatConfig = request.app.state.webchat_config
        return JSONResponse(
            {
                "public": bool(cfg.public),
                "gateway_auth_required": bool(_cached_gateway_token(request)),
            },
        )

    @app.post("/api/webchat/token")
    async def webchat_token(request: Request) -> JSONResponse:
        """Mint a short-lived ``aud=webchat`` JWT for the SPA (`specs/19-channel-webui.md` §2.4).

        Browser-facing endpoint with its own auth model: reachable without the operator
        gateway bearer only when ``webchat.public`` is true (anonymous ``anon:…`` mint).
        Non-public webchat requires ``Authorization: Bearer <gateway_token>`` for owner
        mint; unauthenticated requests return **401** ``webchat_auth_required``. Client
        ``sub`` is honored only when the operator bearer verifies.
        """
        cfg: WebChatConfig = request.app.state.webchat_config
        secret: str | None = request.app.state.webchat_jwt_secret
        if not secret:
            raise HTTPException(status_code=503, detail="webchat_jwt_secret_unconfigured")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        operator_configured = _cached_gateway_token(request)
        operator = bool(operator_configured) and verify_gateway_bearer(
            configured=operator_configured,
            authorization_header=request.headers.get("Authorization"),
        )
        sub_raw = payload.get("sub") if isinstance(payload, dict) else None
        client_sub = sub_raw.strip() if isinstance(sub_raw, str) and sub_raw.strip() else None
        if operator:
            sub = client_sub or "owner"
        elif cfg.public:
            sub = f"anon:{uuid.uuid4().hex}"
        else:
            raise HTTPException(status_code=401, detail="webchat_auth_required")
        token, expires_in = mint_webchat_jwt(
            secret=secret,
            sub=sub,
            ttl_seconds=int(cfg.jwt_ttl_seconds),
        )
        return JSONResponse(
            {
                "access_token": token,
                "token_type": _OAUTH_ACCESS_TOKEN_TYPE,
                "expires_in": expires_in,
            },
        )

    @app.get("/media/{token}")
    async def media_download(
        request: Request,
        token: str,
        _ok: None = Depends(enforce_gateway_auth),
    ) -> FileResponse:
        ws_local: WorkspaceConfig = request.app.state.workspace
        ly: WorkspaceLayout = request.app.state.layout
        conn = request.app.state.sqlite_conn
        media = MediaStore(conn, ly.content_root)
        path = media.resolve_path(token)
        _ = ws_local
        if path is None:
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(path)

    @app.post("/media/upload")
    async def media_upload(_ok: None = Depends(enforce_gateway_auth)) -> JSONResponse:
        return deferred_json("specs/17-gateway.md §2.1 /media/upload")

    @app.post("/api/second_brain/fetch")
    async def api_second_brain_fetch(
        request: Request,
        _ok: None = Depends(enforce_gateway_auth),
    ) -> JSONResponse:
        """HTTPS URL → ``raw/`` (`specs/27-second-brain.md` §2.4) — gateway-only fetch."""
        ws_local: WorkspaceConfig = request.app.state.workspace
        ly: WorkspaceLayout = request.app.state.layout
        trace_local: TraceSink = request.app.state.gateway_trace
        sb_cfg = ws_local.second_brain
        if sb_cfg is None or not sb_cfg.enabled:
            raise HTTPException(status_code=403, detail="second_brain_disabled")
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        url = str(payload.get("url", "")).strip()
        scope = str(payload.get("scope") or sb_cfg.default_scope).strip()
        if not url:
            raise HTTPException(status_code=400, detail="missing_url")
        scope_path = resolve_scope_root(ly.content_root, sb_cfg, scope)
        try:
            out = await fetch_url_to_raw(url=url, scope_root=scope_path, fetch_cfg=sb_cfg.fetch)
        except SecondBrainFetchError as exc:
            host_guess = urlparse(url).hostname or ""
            await _emit_webchat_trace(
                trace_local,
                kind="second_brain.fetch",
                session_id="gateway",
                status="error",
                attrs={
                    "second_brain.scope": scope,
                    "fetch.host": host_guess,
                    "second_brain.paths_touched": [],
                },
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        host_out = str(out.get("host", ""))
        await _emit_webchat_trace(
            trace_local,
            kind="second_brain.fetch",
            session_id="gateway",
            status="ok",
            attrs={
                "second_brain.scope": scope,
                "fetch.host": host_out,
                "second_brain.paths_touched": [
                    f"{display_scope_root_relative(ly.content_root, scope_path)}/raw/{out['raw_relpath']}"
                ],
            },
        )
        return JSONResponse({"ok": True, "data": out})

    @app.post("/webapp/telegram")
    async def webapp_telegram(request: Request) -> JSONResponse:
        """Telegram Web App ``initData`` exchange (`specs/19-channel-webui.md` §2.5).
        Accepts either ``application/json`` ``{"init_data": ...}`` or
        ``application/x-www-form-urlencoded`` with an ``init_data`` field.
        Returns an ``access_token`` payload on success or ``403`` otherwise —
        the raw ``initData`` string is **never** echoed in the response body or
        emitted to logs / traces.
        """
        ws_local: WorkspaceConfig = request.app.state.workspace
        ly: WorkspaceLayout = request.app.state.layout
        cfg: WebChatConfig = request.app.state.webchat_config
        secret: str | None = request.app.state.webchat_jwt_secret
        trace_local: TraceSink = request.app.state.gateway_trace
        if not secret:
            raise HTTPException(status_code=503, detail="webchat_jwt_secret_unconfigured")
        init_data: str | None = None
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                v = payload.get("init_data")
                if isinstance(v, str):
                    init_data = v
        else:
            form = await request.form()
            v = form.get("init_data")
            if isinstance(v, str):
                init_data = v
        if not init_data:
            await _emit_webchat_trace(
                trace_local,
                kind="gateway.webapp.telegram_verify_failed",
                status="invalid",
                attrs={"reason": "missing_init_data"},
            )
            raise HTTPException(status_code=403, detail="forbidden")
        bot_token = await _resolve_webapp_telegram_bot_token(ws_local, content_root=ly.content_root)
        if not bot_token:
            await _emit_webchat_trace(
                trace_local,
                kind="gateway.webapp.telegram_verify_failed",
                status="unconfigured",
                attrs={"reason": "bot_token_unavailable"},
            )
            raise HTTPException(status_code=403, detail="forbidden")
        verified = verify_telegram_init_data(
            bot_token=bot_token,
            init_data=init_data,
            max_age_seconds=WEBAPP_TELEGRAM_INITDATA_MAX_AGE_SECONDS,
        )
        if verified is None:
            await _emit_webchat_trace(
                trace_local,
                kind="gateway.webapp.telegram_verify_failed",
                status="bad_signature",
            )
            raise HTTPException(status_code=403, detail="forbidden")
        sub = "owner"
        user_blob = verified.get("user")
        if isinstance(user_blob, str) and user_blob:
            try:
                user_obj = json.loads(user_blob)
            except (ValueError, TypeError):
                user_obj = None
            if isinstance(user_obj, dict):
                user_id_raw = user_obj.get("id")
                if isinstance(user_id_raw, int):
                    sub = f"tg:{user_id_raw}"
                elif isinstance(user_id_raw, str) and user_id_raw.strip():
                    sub = f"tg:{user_id_raw.strip()}"
        token, expires_in = mint_webchat_jwt(
            secret=secret,
            sub=sub,
            ttl_seconds=int(cfg.jwt_ttl_seconds),
        )
        return JSONResponse(
            {
                "access_token": token,
                "token_type": _OAUTH_ACCESS_TOKEN_TYPE,
                "expires_in": expires_in,
            },
        )

    async def _verify_webapp_init_data(
        request: Request,
        *,
        init_data: str | None,
        trace_local: TraceSink,
        fail_kind: str,
    ) -> dict[str, str] | None:
        """Verify Telegram ``initData`` for Web App share/feedback routes."""
        ws_local: WorkspaceConfig = request.app.state.workspace
        ly: WorkspaceLayout = request.app.state.layout
        if not init_data:
            await _emit_webchat_trace(
                trace_local,
                kind=fail_kind,
                status="invalid",
                attrs={"reason": "missing_init_data"},
            )
            return None
        bot_token = await _resolve_webapp_telegram_bot_token(ws_local, content_root=ly.content_root)
        if not bot_token:
            await _emit_webchat_trace(
                trace_local,
                kind=fail_kind,
                status="unconfigured",
                attrs={"reason": "bot_token_unavailable"},
            )
            return None
        verified = verify_telegram_init_data(bot_token=bot_token, init_data=init_data)
        if verified is None:
            await _emit_webchat_trace(trace_local, kind=fail_kind, status="bad_signature")
            return None
        return verified

    def _telegram_user_id_from_verified(verified: dict[str, str]) -> str:
        user_blob = verified.get("user")
        if isinstance(user_blob, str) and user_blob:
            try:
                user_obj = json.loads(user_blob)
            except (ValueError, TypeError):
                user_obj = None
            if isinstance(user_obj, dict):
                user_id_raw = user_obj.get("id")
                if isinstance(user_id_raw, int):
                    return str(user_id_raw)
                if isinstance(user_id_raw, str) and user_id_raw.strip():
                    return user_id_raw.strip()
        return "owner"

    @app.get("/webapp/share")
    async def webapp_share_get(request: Request, token: str = Query(default="")) -> Response:
        """Serve Share Web App shell (`plan/telegram-webapp-prd.md` §S)."""
        _ = request, token
        return _webapp_serve_static("share/index.html")

    @app.post("/webapp/share/payload")
    async def webapp_share_payload(request: Request) -> JSONResponse:
        """Return share payload after ``initData`` verify; burn token once."""
        conn = request.app.state.sqlite_conn
        trace_local: TraceSink = request.app.state.gateway_trace
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        token = str(body.get("token", "")).strip()
        init_data = body.get("init_data")
        init_str = init_data if isinstance(init_data, str) else None
        verified = await _verify_webapp_init_data(
            request,
            init_data=init_str,
            trace_local=trace_local,
            fail_kind="gateway.webapp.share_verify_failed",
        )
        if verified is None:
            raise HTTPException(status_code=403, detail="forbidden")
        payload = await asyncio.to_thread(
            load_webapp_dispatcher_payload,
            conn,
            token=token,
            expected_kind="webapp_share",
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="not_found")
        bound_user = str(payload.get("user_id", ""))
        if bound_user and bound_user != _telegram_user_id_from_verified(verified):
            raise HTTPException(status_code=403, detail="forbidden")
        share_text = str(payload.get("share_text", ""))
        await asyncio.to_thread(consume_webapp_dispatcher_token, conn, token=token)
        await _emit_webchat_trace(
            trace_local,
            kind="gateway.webapp.share_payload",
            status="ok",
            attrs={"target_turn_id": str(payload.get("gateway_message_id", ""))},
        )
        return JSONResponse({"text": share_text, "url": "", "files": []})

    @app.get("/webapp/feedback")
    async def webapp_feedback_get(request: Request, token: str = Query(default="")) -> Response:
        """Serve Feedback Web App shell (`plan/telegram-webapp-prd.md` §F)."""
        _ = request, token
        return _webapp_serve_static("feedback/index.html")

    @app.post("/webapp/feedback/submit")
    async def webapp_feedback_submit(request: Request) -> JSONResponse:
        """Persist structured feedback (Telegram ``initData`` or webchat JWT)."""
        ws_local: WorkspaceConfig = request.app.state.workspace
        ly: WorkspaceLayout = request.app.state.layout
        conn = request.app.state.sqlite_conn
        trace_local: TraceSink = request.app.state.gateway_trace
        secret: str | None = request.app.state.webchat_jwt_secret
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        token = str(body.get("token", "")).strip()
        fields_raw = body.get("fields")
        fields = fields_raw if isinstance(fields_raw, dict) else {}
        body_text = str(fields.get("body_text", fields.get("free_text", ""))).strip()
        dropdowns_raw = fields.get("dropdowns")
        dropdowns = dropdowns_raw if isinstance(dropdowns_raw, dict) else {}
        for key in ("what_wrong", "severity"):
            if fields.get(key):
                dropdowns[key] = fields[key]
        submission_key = body.get("submission_key")
        sub_key = submission_key if isinstance(submission_key, str) else None
        if not body_text and not dropdowns:
            raise HTTPException(status_code=400, detail="empty_feedback")
        init_data = body.get("init_data")
        init_str = init_data if isinstance(init_data, str) else None
        channel = "telegram"
        user_id = "owner"
        if init_str:
            verified = await _verify_webapp_init_data(
                request,
                init_data=init_str,
                trace_local=trace_local,
                fail_kind="gateway.webapp.feedback_verify_failed",
            )
            if verified is None:
                raise HTTPException(status_code=403, detail="forbidden")
            user_id = _telegram_user_id_from_verified(verified)
        else:
            channel = "webchat"
            bearer = request.headers.get("Authorization")
            if not secret or not bearer:
                raise HTTPException(status_code=403, detail="forbidden")
            claims = verify_webchat_jwt(secret=secret, token=bearer.removeprefix("Bearer ").strip())
            if claims is None:
                raise HTTPException(status_code=403, detail="forbidden")
            user_id = claims.sub
        payload = None
        if token:
            payload = await asyncio.to_thread(
                load_webapp_dispatcher_payload,
                conn,
                token=token,
                expected_kind="webapp_feedback",
            )
            if payload is None and channel == "telegram":
                if sub_key:
                    existing = await asyncio.to_thread(
                        lambda: conn.execute(
                            "SELECT feedback_id FROM structured_feedback WHERE submission_key = ?",
                            (sub_key,),
                        ).fetchone(),
                    )
                    if existing is not None:
                        return JSONResponse({"ok": True, "feedback_id": str(existing[0])})
                raise HTTPException(status_code=404, detail="not_found")
        target_turn = str(
            body.get("target_turn_id") or (payload or {}).get("gateway_message_id") or "",
        ).strip()
        if not target_turn:
            raise HTTPException(status_code=400, detail="missing_target")
        if payload is not None:
            bound_user = str(payload.get("user_id", ""))
            if bound_user and bound_user != user_id:
                raise HTTPException(status_code=403, detail="forbidden")
            if channel == "telegram" and token:
                await asyncio.to_thread(consume_webapp_dispatcher_token, conn, token=token)
        platform_mid = (payload or {}).get("platform_message_id")
        fid = await asyncio.to_thread(
            insert_structured_feedback,
            conn,
            target_turn_id=target_turn,
            user_id=user_id,
            channel=channel,
            platform_message_id=str(platform_mid) if platform_mid is not None else None,
            body_text=body_text,
            dropdowns=dropdowns,
            submission_key=sub_key,
        )
        policy = trace_redaction_policy_for(ws_local)
        trace_body = redact_attrs({"body_text": body_text}, policy).get("body_text", "")
        await _emit_webchat_trace(
            trace_local,
            kind="structured_feedback_submit",
            status="ok",
            attrs={
                "feedback_id": fid or "",
                "target_turn_id": target_turn,
                "channel": channel,
                "body_text": trace_body,
            },
        )
        if fid:
            await asyncio.to_thread(
                mirror_structured_feedback_to_events,
                conn,
                feedback_id=fid,
                target_turn_id=target_turn,
                channel=channel,
                body_text=body_text,
                dropdowns=dropdowns,
            )
        _ = ly
        return JSONResponse({"ok": True, "feedback_id": fid})

    @app.get("/webapp/viewer")
    async def webapp_viewer_get(request: Request, token: str = Query(default="")) -> Response:
        """Serve rich artifact viewer Mini App shell (``specs/29-openui.md``)."""
        _ = request, token
        return _webapp_serve_static("viewer/index.html")

    @app.post("/webapp/viewer/payload")
    async def webapp_viewer_payload(request: Request) -> JSONResponse:
        """Return viewer artifact payload after ``initData`` verify."""
        conn = request.app.state.sqlite_conn
        trace_local: TraceSink = request.app.state.gateway_trace
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        token = str(body.get("token", "")).strip()
        init_data = body.get("init_data")
        init_str = init_data if isinstance(init_data, str) else None
        verified = await _verify_webapp_init_data(
            request,
            init_data=init_str,
            trace_local=trace_local,
            fail_kind="gateway.webapp.viewer_verify_failed",
        )
        if verified is None:
            raise HTTPException(status_code=403, detail="forbidden")
        payload = await asyncio.to_thread(load_webapp_viewer_payload, conn, token=token)
        if payload is None:
            raise HTTPException(status_code=404, detail="not_found")
        bound_user = str(payload.get("user_id", ""))
        if bound_user and bound_user != _telegram_user_id_from_verified(verified):
            raise HTTPException(status_code=403, detail="forbidden")
        view = str(payload.get("view", ""))
        if view != "stream":
            await asyncio.to_thread(consume_webapp_dispatcher_token, conn, token=token)
        await _emit_webchat_trace(
            trace_local,
            kind="gateway.webapp.viewer_payload",
            status="ok",
            attrs={"view": view, "target_turn_id": str(payload.get("gateway_message_id", ""))},
        )
        ws_local: WorkspaceConfig = request.app.state.workspace
        return JSONResponse(
            {
                "view": view,
                "view_data": payload.get("view_data")
                if isinstance(payload.get("view_data"), dict)
                else {},
                "stream_id": payload.get("stream_id"),
                "share_to_story": webapp_share_to_story_enabled(ws_local),
            },
        )

    async def _verify_viewer_stream_token(
        request: Request,
        *,
        token: str,
        stream_id: str,
        trace_local: TraceSink,
    ) -> dict[str, Any]:
        init_data = request.headers.get("X-Telegram-Init-Data") or request.query_params.get(
            "init_data",
            "",
        )
        init_str = init_data if isinstance(init_data, str) and init_data else None
        if init_str is None and request.method in {"POST", "PUT", "PATCH"}:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                raw = body.get("init_data")
                init_str = raw if isinstance(raw, str) else None
        verified = await _verify_webapp_init_data(
            request,
            init_data=init_str,
            trace_local=trace_local,
            fail_kind="gateway.webapp.viewer_stream_verify_failed",
        )
        if verified is None:
            raise HTTPException(status_code=403, detail="forbidden")
        conn = request.app.state.sqlite_conn
        payload = await asyncio.to_thread(load_webapp_viewer_payload, conn, token=token.strip())
        if payload is None:
            raise HTTPException(status_code=404, detail="not_found")
        if str(payload.get("stream_id", "")) != stream_id:
            raise HTTPException(status_code=403, detail="forbidden")
        bound_user = str(payload.get("user_id", ""))
        if bound_user and bound_user != _telegram_user_id_from_verified(verified):
            raise HTTPException(status_code=403, detail="forbidden")
        return payload

    @app.get("/webapp/viewer/stream/{stream_id}/poll")
    async def webapp_viewer_stream_poll(
        request: Request,
        stream_id: str,
        token: str = Query(default=""),
        offset: int = Query(default=0),
    ) -> JSONResponse:
        """Poll incremental stream chunks for the viewer stream layout."""
        trace_local: TraceSink = request.app.state.gateway_trace
        await _verify_viewer_stream_token(
            request,
            token=token,
            stream_id=stream_id,
            trace_local=trace_local,
        )
        snap = viewer_stream_snapshot(stream_id, offset=max(0, int(offset)))
        return JSONResponse(snap)

    @app.get("/webapp/viewer/stream/{stream_id}")
    async def webapp_viewer_stream_sse(
        request: Request,
        stream_id: str,
        token: str = Query(default=""),
    ) -> StreamingResponse:
        """SSE stream of incremental viewer output chunks."""
        trace_local: TraceSink = request.app.state.gateway_trace
        await _verify_viewer_stream_token(
            request,
            token=token,
            stream_id=stream_id,
            trace_local=trace_local,
        )

        async def _events() -> AsyncIterator[str]:
            offset = 0
            while True:
                snap = viewer_stream_snapshot(stream_id, offset=offset)
                for chunk in snap["chunks"]:
                    yield f"data: {json.dumps({'chunk': chunk}, separators=(',', ':'))}\n\n"
                offset = int(snap["next_offset"])
                if snap["done"]:
                    yield f"data: {json.dumps({'done': True}, separators=(',', ':'))}\n\n"
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(_events(), media_type="text/event-stream")

    @app.post("/api/webchat/qa")
    async def webchat_qa_action(request: Request) -> JSONResponse:
        """Webchat QA bar actions (thumbs toggle + regen) without ``initData``."""
        conn = request.app.state.sqlite_conn
        secret: str | None = request.app.state.webchat_jwt_secret
        router: ChannelRouter = request.app.state.gateway_router
        if not secret:
            raise HTTPException(status_code=503, detail="webchat_jwt_secret_unconfigured")
        bearer = request.headers.get("Authorization")
        claims = verify_webchat_jwt(
            secret=secret, token=(bearer or "").removeprefix("Bearer ").strip()
        )
        if claims is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="invalid_json")
        action = str(body.get("action", "")).strip().lower()
        session_id = str(body.get("session_id", "")).strip()
        gw_mid_raw = body.get("gateway_message_id")
        if action not in {"up", "down", "regen"} or not session_id:
            raise HTTPException(status_code=400, detail="invalid_request")
        if action == "regen":
            await router._sessions.enqueue_dispatch(
                session_id,
                correlation_id=str(gw_mid_raw or ""),
                queue_mode=router._queue_mode,
                dispatch=router._run_turn,
            )
            return JSONResponse({"ok": True, "toast": "Regenerating…"})
        if gw_mid_raw is None:
            raise HTTPException(status_code=400, detail="missing_gateway_message_id")
        gateway_mid = int(gw_mid_raw)
        platform_mid = int(body.get("platform_message_id") or 0)
        current = await asyncio.to_thread(
            resolve_thumbs_polarity,
            conn,
            user_id=claims.sub,
            platform_message_id=platform_mid,
            target_turn_id=str(gateway_mid),
        )
        polarity: Literal["up", "down"] = "up" if action == "up" else "down"
        kind, extra = resolve_thumbs_transition(action=polarity, current=current)
        payload_fb: dict[str, object] = {
            "channel": "webchat",
            "user_id": claims.sub,
            "platform_message_id": platform_mid,
        }
        payload_fb.update(extra)
        await asyncio.to_thread(
            insert_feedback_event,
            conn,
            kind=kind,
            target_turn_id=str(gateway_mid),
            schema_version=1,
            payload=payload_fb,
        )
        toast = (
            "Marked helpful"
            if action == "up" and not kind.endswith("_clear")
            else "Logged feedback"
        )
        if kind.endswith("_clear"):
            toast = "Vote cleared"
        return JSONResponse({"ok": True, "kind": kind, "toast": toast})

    @app.get("/webapp")
    async def webapp_root() -> Response:
        return _webapp_serve_static("index.html")

    @app.get("/webapp/")
    async def webapp_root_slash() -> Response:
        return _webapp_serve_static("index.html")

    @app.get("/webapp/{asset_path:path}")
    async def webapp_static(asset_path: str) -> Response:
        return _webapp_serve_static(asset_path or "index.html")

    @app.get("/openui/{openui_token}")
    async def openui_get(request: Request, openui_token: str) -> HTMLResponse:
        """Serve sanitised OpenUI HTML with CSP (`specs/29-openui.md` §2.2, §8.2)."""
        ws_local: WorkspaceConfig = request.app.state.workspace
        secret: str = str(getattr(request.app.state, "openui_secret", "") or "")
        store: OpenUIStore = request.app.state.openui_store
        status, payload = verify_token_status(
            secret=secret, token=openui_token, expected_scope="render"
        )
        if status == "expired":
            return HTMLResponse(
                content="<p>This form has expired.</p>",
                status_code=410,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        if status != "ok" or payload is None:
            raise HTTPException(status_code=404, detail="not_found")
        rid = str(payload["rid"])
        rec = store.get(rid)
        if rec is None:
            return HTMLResponse(
                content="<p>This form has expired.</p>",
                status_code=410,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        base = str(request.base_url).rstrip("/")
        ou_cfg = effective_openui_config(ws_local.openui)
        csp = build_content_security_policy(
            allowed_asset_origins=ou_cfg.allowed_asset_origins,
            gateway_origin=base,
        )
        doc = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f"<title>OpenUI</title></head><body>{rec.sanitised_html}</body></html>"
        )
        return HTMLResponse(content=doc, headers={"Content-Security-Policy": csp})

    @app.post("/openui/callback")
    async def openui_callback(
        request: Request,
        token: str = Query(""),
    ) -> HTMLResponse:
        """Accept form POST for OpenUI submit tokens (`specs/29-openui.md` §2.2)."""
        ws_local: WorkspaceConfig = request.app.state.workspace
        secret: str = str(getattr(request.app.state, "openui_secret", "") or "")
        store: OpenUIStore = request.app.state.openui_store
        router_local: ChannelRouter = request.app.state.gateway_router
        trace_local: TraceSink = request.app.state.gateway_trace
        if not token.strip():
            return HTMLResponse(
                content="<p>This form has expired.</p>",
                status_code=410,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        status, payload = verify_token_status(secret=secret, token=token, expected_scope="submit")
        if status == "expired":
            return HTMLResponse(
                content="<p>This form has expired.</p>",
                status_code=410,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        if status != "ok" or payload is None:
            return HTMLResponse(
                content="<p>This form has expired.</p>",
                status_code=410,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        rid = str(payload["rid"])
        rec = store.get(rid)
        if rec is None:
            return HTMLResponse(
                content="<p>This form has expired.</p>",
                status_code=410,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        body = await request.body()
        fields = parse_query_dict(body)
        if rec.submit_consumed:
            return HTMLResponse(
                content="<p>This form was already submitted.</p>",
                status_code=409,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        if not store.mark_submit_consumed(rid):
            return HTMLResponse(
                content="<p>This form was already submitted.</p>",
                status_code=409,
                headers={"Content-Security-Policy": "default-src 'none'; script-src 'none'"},
            )
        form_id = str(fields.get("form_id") or "openui:agent:form:submit")
        parent_message_id = str(fields.get("parent_message_id") or rec.message_id)
        conn = request.app.state.sqlite_conn
        row = conn.execute(
            "SELECT scope_key, user_id FROM gateway_sessions WHERE session_id = ?",
            (rec.session_id,),
        ).fetchone()
        if row:
            scope_key, user_id = str(row[0]), str(row[1])
        else:
            scope_key = f"{rec.channel}:openui"
            user_id = "openui"
        ou_cfg = effective_openui_config(ws_local.openui)
        base = str(request.base_url).rstrip("/")
        csp = build_content_security_policy(
            allowed_asset_origins=ou_cfg.allowed_asset_origins,
            gateway_origin=base,
        )
        dispatch = build_openui_dispatch_payload(
            channel=rec.channel,
            user_id=user_id,
            session_id=rec.session_id,
            parent_message_id=parent_message_id,
            form_id=form_id,
            fields=fields,
        )
        dispatch["metadata"]["session_scope_override"] = scope_key
        await router_local.route_incoming(IncomingMessage(**dispatch))
        now = time.time_ns()
        await trace_local.emit(
            TraceEvent(
                kind="openui_callback",
                span_id=uuid.uuid4().hex,
                parent_span_id=None,
                session_id=rec.session_id,
                turn_id=rec.message_id,
                tier=None,
                ts_start_ns=now,
                ts_end_ns=now,
                status="ok",
                attrs={
                    "parent_message_id": parent_message_id,
                    "form_id": form_id,
                    "route": dispatch["metadata"].get("openui_route", ""),
                    "fields_keys": sorted(fields.keys()),
                },
            ),
        )
        return HTMLResponse(
            content="<p>Received.</p>",
            status_code=200,
            headers={"Content-Security-Policy": csp},
        )

    _mount_mission_control_spa(app)

    return app
