"""Starlette ASGI app for the egress LLM proxy.

Module: sevn.proxy.app
Depends: httpx, starlette, sevn.proxy.auth, sevn.proxy.forward, sevn.proxy.settings

Exports:
    create_app — ASGI factory for uvicorn ``--factory`` (``SEVN_HOME`` workspace boot).

Examples:
    >>> from sevn.proxy.app import create_app
    >>> from sevn.proxy.settings import ProxySettings
    >>> from starlette.applications import Starlette
    >>> isinstance(create_app(settings=ProxySettings()), Starlette)
    True
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from loguru import logger
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from sevn.config.loader import load_workspace, resolve_sevn_json_path
from sevn.config.model_resolution import (
    is_minimax_model,
    resolve_wire_model_id,
)
from sevn.config.provider_registry import resolve_provider_for_model_id
from sevn.config.sections.providers import resolve_auth_mode
from sevn.config.workspace_config import SecretsBackendSectionConfig, WorkspaceConfig
from sevn.logging.setup import maybe_boot_service_logging
from sevn.proxy.anthropic_body import normalize_anthropic_request_body
from sevn.proxy.auth import llm_post_auth_failure
from sevn.proxy.bedrock_converse import converse_via_bedrock
from sevn.proxy.codex_translation import (
    aggregate_responses_sse,
    translate_chat_to_responses_request,
    translate_responses_sse_to_chat_stream,
    translate_responses_to_chat_completion,
)
from sevn.proxy.codex_transport import build_codex_request_headers, codex_responses_url
from sevn.proxy.credentials import (
    ProviderCredentials,
    build_proxy_settings_sync,
    credential_unresolved_detail,
    resolve_oauth_request_credential_async,
    resolve_request_credential,
)
from sevn.proxy.forward import post_json, post_sse_stream
from sevn.proxy.http_client import create_proxy_http_client
from sevn.proxy.integration.router import integration_post
from sevn.proxy.oauth_lifecycle import OauthCredentialMissingError
from sevn.proxy.settings import ProxySettings
from sevn.proxy.web_forward import brave_search_json, web_fetch_json
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.factory import secrets_chain_from_workspace


def _bootstrap_from_operator_home() -> tuple[ProxySettings, WorkspaceConfig, Path] | None:
    """Load workspace, logging, and proxy settings when ``SEVN_HOME`` is bound.

    Returns:
        tuple[ProxySettings, WorkspaceConfig, Path] | None: Boot tuple when
        ``sevn.json`` resolves; ``None`` for env-only dev without a workspace.

    Examples:
        >>> _bootstrap_from_operator_home.__name__
        '_bootstrap_from_operator_home'
    """
    sevn_json = resolve_sevn_json_path()
    if sevn_json is None:
        return None
    workspace_config, layout = load_workspace(sevn_json=sevn_json)
    maybe_boot_service_logging("proxy", layout.logs_dir)
    settings = build_proxy_settings_sync(
        workspace_config=workspace_config,
        content_root=layout.content_root,
    )
    return settings, workspace_config, layout.content_root


def create_app(
    *,
    settings: ProxySettings | None = None,
    workspace_config: WorkspaceConfig | None = None,
    content_root: Path | None = None,
) -> Starlette:
    """Build the proxy ASGI app.

    When called with no arguments (uvicorn ``--factory``), resolves
    ``{SEVN_HOME}/workspace/sevn.json``, rotates ``proxy.log``, configures loguru,
    and builds settings from the secrets chain per ``specs/06-secrets.md`` §2.4.

    Args:
        settings (ProxySettings | None): Explicit settings for tests; when omitted
            with no workspace, reads process environment only.
        workspace_config (WorkspaceConfig | None): When set with ``content_root``,
            wires ``ResolvedSecretsCache`` on ``app.state.secrets_cache``.
        content_root (Path | None): Workspace content anchor for encrypted file paths.

    Returns:
        Starlette: Application with ``app.state.settings`` populated at startup.

    Examples:
        >>> from sevn.proxy.app import create_app
        >>> from starlette.applications import Starlette
        >>> isinstance(create_app(settings=ProxySettings()), Starlette)
        True
    """
    resolved_settings = settings
    ws_cfg = workspace_config
    root = content_root

    if resolved_settings is None and ws_cfg is None and root is None:
        booted = _bootstrap_from_operator_home()
        if booted is not None:
            resolved_settings, ws_cfg, root = booted
            from sevn.tracing.otel_pipeline import configure_proxy_otel

            configure_proxy_otel(ws_cfg)

    resolved = resolved_settings if resolved_settings is not None else ProxySettings()

    async def sse_or_json(
        *,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        stream: bool,
    ) -> Response:
        if stream:
            client, upstream = await post_sse_stream(url=url, headers=headers, body=body)
            media_type = upstream.headers.get("content-type", "text/event-stream")

            async def iterate() -> AsyncIterator[bytes]:
                try:
                    if upstream.status_code >= 400:
                        yield await upstream.aread()
                        return
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(
                iterate(),
                status_code=upstream.status_code,
                media_type=media_type,
            )
        upstream = await post_json(url=url, headers=headers, body=body)
        ct = upstream.headers.get("content-type", "application/json")
        return Response(content=upstream.content, status_code=upstream.status_code, media_type=ct)

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def bedrock_converse(request: Request) -> JSONResponse:
        cfg: ProxySettings = request.app.state.settings
        try:
            raw_body = await request.json()
        except Exception:
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)
        if not isinstance(raw_body, dict):
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)
        try:
            result = await asyncio.to_thread(converse_via_bedrock, cfg, raw_body)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except RuntimeError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)
        return JSONResponse(result)

    def _anthropic_messages_url(base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    async def anthropic_messages(request: Request) -> Response:
        cfg: ProxySettings = request.app.state.settings
        ws = getattr(request.app.state, "workspace_config", None)
        workspace = ws if isinstance(ws, WorkspaceConfig) else WorkspaceConfig.minimal()
        raw_body = await request.json()
        if not isinstance(raw_body, dict):
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)
        body = normalize_anthropic_request_body(dict(raw_body))
        model_raw = body.get("model")
        model_id = str(model_raw) if model_raw is not None else ""
        provider_name = resolve_provider_for_model_id(workspace, model_id)
        api_key, base_url = resolve_request_credential(
            workspace,
            request.app.state,
            model_id,
            "/llm/anthropic/messages",
        )
        is_minimax = is_minimax_model(model_id)
        if is_minimax:
            body["model"] = resolve_wire_model_id(model_id)
        if not api_key:
            return JSONResponse(
                {"detail": credential_unresolved_detail(provider_name)},
                status_code=503,
            )
        url = _anthropic_messages_url(base_url)
        headers = {
            "x-api-key": api_key,
            "anthropic-version": cfg.anthropic_version,
            "content-type": "application/json",
        }
        stream = body.get("stream") is True
        logger.info(
            "proxy route /llm/anthropic/messages catalog_model={catalog!r} "
            "wire_model={wire!r} base_url={base!r} minimax={minimax} stream={stream} "
            "provider={provider!r}",
            catalog=model_id,
            wire=body.get("model"),
            base=base_url,
            minimax=is_minimax,
            stream=stream,
            provider=provider_name,
        )
        return await sse_or_json(url=url, headers=headers, body=body, stream=stream)

    async def openai_chat_completions(request: Request) -> Response:
        ws = getattr(request.app.state, "workspace_config", None)
        workspace = ws if isinstance(ws, WorkspaceConfig) else WorkspaceConfig.minimal()
        raw_body = await request.json()
        if not isinstance(raw_body, dict):
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)

        model_raw = raw_body.get("model")
        model_id = str(model_raw) if model_raw is not None else ""
        provider_name = resolve_provider_for_model_id(workspace, model_id)
        stream = raw_body.get("stream") is True

        if (
            provider_name == "openai"
            and resolve_auth_mode(workspace.providers, "openai") == "oauth"
        ):
            try:
                access_token, account_id, _base = await resolve_oauth_request_credential_async(
                    workspace,
                    request.app.state,
                    model_id,
                    "/llm/openai/chat/completions",
                )
            except OauthCredentialMissingError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=503)

            incoming_headers = {k: v for k, v in request.headers.items() if isinstance(v, str)}
            headers = build_codex_request_headers(
                access_token=access_token,
                account_id=account_id,
                incoming=incoming_headers,
            )
            body = translate_chat_to_responses_request(dict(raw_body))
            url = codex_responses_url()
            logger.info(
                "proxy route /llm/openai/chat/completions catalog_model={catalog!r} "
                "wire_model={wire!r} base_url={base!r} minimax={minimax} stream={stream} "
                "provider={provider!r} auth_mode=oauth wire_format=responses",
                catalog=model_id,
                wire=body.get("model"),
                base=url,
                minimax=False,
                stream=stream,
                provider=provider_name,
            )
            if stream:
                client, upstream = await post_sse_stream(url=url, headers=headers, body=body)
                media_type = upstream.headers.get("content-type", "text/event-stream")

                async def iterate_codex() -> AsyncIterator[bytes]:
                    try:
                        if upstream.status_code >= 400:
                            yield await upstream.aread()
                            return
                        buffer = b""
                        async for chunk in upstream.aiter_bytes():
                            buffer += chunk
                            text = buffer.decode("utf-8", errors="replace")
                            if "\n\n" in text or text.endswith("\n"):
                                for out_chunk in translate_responses_sse_to_chat_stream(text):
                                    yield out_chunk.encode("utf-8")
                                buffer = b""
                        if buffer:
                            text = buffer.decode("utf-8", errors="replace")
                            for out_chunk in translate_responses_sse_to_chat_stream(text):
                                yield out_chunk.encode("utf-8")
                    finally:
                        await upstream.aclose()
                        await client.aclose()

                return StreamingResponse(
                    iterate_codex(),
                    status_code=upstream.status_code,
                    media_type=media_type,
                )

            # Codex (backend-api/codex/responses) has no non-streaming mode: it
            # rejects stream=false with 400 {"detail":"Stream must be set to true"}.
            # For a non-streaming caller we always stream upstream, buffer the SSE,
            # aggregate the terminal Responses object, then return a single
            # chat-completion JSON — the same shape the old post_json branch returned.
            body["stream"] = True
            client, upstream = await post_sse_stream(url=url, headers=headers, body=body)
            try:
                if upstream.status_code >= 400:
                    raw_error = await upstream.aread()
                    ct = upstream.headers.get("content-type", "application/json")
                    return Response(
                        content=raw_error,
                        status_code=upstream.status_code,
                        media_type=ct,
                    )
                raw_sse = (await upstream.aread()).decode("utf-8", errors="replace")
            finally:
                await upstream.aclose()
                await client.aclose()
            try:
                responses_payload = aggregate_responses_sse(raw_sse)
                chat_payload = translate_responses_to_chat_completion(responses_payload)
            except (ValueError, KeyError, TypeError) as exc:
                # The upstream SSE body carries no auth secrets (tokens live in the
                # request headers, never the response stream), so a short head
                # snippet is safe to log; truncate to keep it one line and avoid
                # dumping large reasoning.encrypted_content blobs.
                snippet = raw_sse[:300].replace("\n", "\\n")
                logger.warning(
                    "proxy codex oauth non-stream aggregation failed "
                    "(bytes={bytes} error={error_type}: {error}); "
                    "raw_head={snippet!r}; returning 502",
                    bytes=len(raw_sse),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    snippet=snippet,
                )
                return JSONResponse(
                    {"detail": "invalid upstream Responses stream"},
                    status_code=502,
                )
            return JSONResponse(chat_payload)

        api_key, base_url = resolve_request_credential(
            workspace,
            request.app.state,
            model_id,
            "/llm/openai/chat/completions",
        )
        is_minimax = is_minimax_model(model_id)
        if is_minimax:
            raw_body["model"] = resolve_wire_model_id(model_id)
        if not api_key:
            return JSONResponse(
                {"detail": credential_unresolved_detail(provider_name)},
                status_code=503,
            )

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        logger.info(
            "proxy route /llm/openai/chat/completions catalog_model={catalog!r} "
            "wire_model={wire!r} base_url={base!r} minimax={minimax} stream={stream} "
            "provider={provider!r}",
            catalog=model_id,
            wire=raw_body.get("model"),
            base=base_url,
            minimax=is_minimax,
            stream=stream,
            provider=provider_name,
        )
        return await sse_or_json(url=url, headers=headers, body=raw_body, stream=stream)

    async def openai_responses(request: Request) -> Response:
        cfg: ProxySettings = request.app.state.settings
        if not cfg.openai_api_key:
            return JSONResponse({"detail": "openai not configured"}, status_code=503)
        raw_body = await request.json()
        if not isinstance(raw_body, dict):
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)
        url = f"{cfg.openai_base_url.rstrip('/')}/responses"
        headers = {
            "authorization": f"Bearer {cfg.openai_api_key}",
            "content-type": "application/json",
        }
        stream = raw_body.get("stream") is True
        return await sse_or_json(url=url, headers=headers, body=raw_body, stream=stream)

    async def web_fetch(request: Request) -> Response:
        cfg: ProxySettings = request.app.state.settings
        raw_body = await request.json()
        if not isinstance(raw_body, dict):
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)
        http_client = getattr(request.app.state, "http_client", None)
        status, payload = await web_fetch_json(raw_body, settings=cfg, client=http_client)
        return JSONResponse(payload, status_code=status)

    async def web_brave_search(request: Request) -> Response:
        cfg: ProxySettings = request.app.state.settings
        raw_body = await request.json()
        if not isinstance(raw_body, dict):
            return JSONResponse({"detail": "expected JSON object body"}, status_code=422)
        http_client = getattr(request.app.state, "http_client", None)
        status, payload = await brave_search_json(raw_body, settings=cfg, client=http_client)
        return JSONResponse(payload, status_code=status)

    class GuardMiddleware(BaseHTTPMiddleware):
        def __init__(self, app: ASGIApp, *, settings: ProxySettings) -> None:
            super().__init__(app)
            self._settings = settings

        async def dispatch(
            self,
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            blocked = llm_post_auth_failure(request, self._settings.proxy_shared_secret)
            if blocked is not None:
                return blocked
            return await call_next(request)

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/llm/anthropic/messages", anthropic_messages, methods=["POST"]),
        Route("/llm/openai/chat/completions", openai_chat_completions, methods=["POST"]),
        Route("/llm/openai/responses", openai_responses, methods=["POST"]),
        Route("/llm/bedrock/converse", bedrock_converse, methods=["POST"]),
        Route("/web/fetch", web_fetch, methods=["POST"]),
        Route("/web/brave/search", web_brave_search, methods=["POST"]),
        Route("/integration", integration_post, methods=["POST"]),
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.http_client = create_proxy_http_client()
        try:
            yield
        finally:
            await app.state.http_client.aclose()

    application = Starlette(routes=routes, lifespan=lifespan)
    application.state.settings = resolved
    application.state.workspace_config = ws_cfg
    application.state.secrets_cache = None
    pc = getattr(resolved, "provider_credentials", None)
    application.state.provider_credentials = (
        pc if isinstance(pc, ProviderCredentials) else ProviderCredentials()
    )
    application.state._provider_resolve_cache = {}
    if ws_cfg is not None and root is not None:
        sec = ws_cfg.secrets_backend
        chain = secrets_chain_from_workspace(root, sec)
        eff = sec or SecretsBackendSectionConfig()
        application.state.secrets_cache = ResolvedSecretsCache(
            chain,
            ttl_seconds=eff.cache_ttl_seconds,
        )
    application.add_middleware(GuardMiddleware, settings=resolved)
    return application
