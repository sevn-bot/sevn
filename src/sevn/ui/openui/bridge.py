"""OpenUIBridge orchestration (`specs/29-openui.md` §2.3, §4).
Module: sevn.ui.openui.bridge
Depends: secrets, time, pathlib, urllib.parse, re
Exports:
    build_content_security_policy — CSP header value for §8.2.
    inject_submit_token_into_html — rewrite ``/openui/callback`` actions.
    OpenUIBridge — async ``render`` entrypoint.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.ui.openui.models import (
    OpenUIConfig,
    OpenUIRenderError,
    OpenUIRenderResult,
    OpenUIRuntimeDeps,
    OutputMode,
    RasteriseCaps,
)
from sevn.ui.openui.rasteriser import rasterise_pdf_bytes, rasterise_png_bytes
from sevn.ui.openui.sanitiser import sanitise
from sevn.ui.openui.store import OpenUIRecord, OpenUIStore
from sevn.ui.openui.tokens import sign_token

if TYPE_CHECKING:
    from sevn.ui.openui.models import CapStatus
_ACTION_RE = re.compile(
    r"""action\s*=\s*(?P<q>['"])(?P<base>/openui/callback)(?P<rest>[^'"]*)\1""",
    re.IGNORECASE,
)


def build_content_security_policy(
    *,
    allowed_asset_origins: tuple[str, ...],
    gateway_origin: str,
) -> str:
    """Assemble a CSP value for OpenUI shells (`specs/29-openui.md` §8.2, PRD 10 §5.5).
    Args:
        allowed_asset_origins (tuple[str, ...]): Extra ``img-src`` / ``font-src`` / ``style-src`` origins.
        gateway_origin (str): Gateway public origin (no trailing slash) for ``frame-ancestors``.
    Returns:
        str: Single ``Content-Security-Policy`` header value.
    Examples:
        >>> "script-src 'none'" in build_content_security_policy(
        ...     allowed_asset_origins=(), gateway_origin="https://gw.example"
        ... )
        True
    """
    go = gateway_origin.strip().rstrip("/")
    extras = " ".join(f"{o.strip().rstrip('/')}" for o in allowed_asset_origins if str(o).strip())
    img = f"'self' data: {extras}".strip()
    font = f"'self' data: {extras}".strip()
    style = f"'self' 'unsafe-inline' {extras}".strip()
    fa = f"{go} https://t.me" if go else "https://t.me"
    return (
        f"default-src 'self' 'unsafe-inline'; "
        f"script-src 'none'; "
        f"img-src {img}; "
        f"font-src {font}; "
        f"style-src {style}; "
        f"connect-src 'self'; "
        f"frame-src 'none'; "
        f"frame-ancestors {fa}"
    )


def inject_submit_token_into_html(html: str, submit_token: str) -> str:
    """Ensure every form posts to ``/openui/callback?token=…`` (`specs/29-openui.md` §5.8).
    Args:
        html (str): Sanitised HTML containing ``action="/openui/callback"`` forms.
        submit_token (str): URL-encoded submit capability token.
    Returns:
        str: HTML with query tokens appended to matching form actions.
    Examples:
        >>> "token=tok" in inject_submit_token_into_html(
        ...     '<form action="/openui/callback"></form>', "tok"
        ... )
        True
    """
    enc = quote(submit_token, safe="")

    def _sub(m: re.Match[str]) -> str:
        q = m.group("q")
        rest = m.group("rest") or ""
        if "token=" in rest:
            return m.group(0)
        if rest.startswith("?"):
            return f"action={q}{m.group('base')}{rest}&token={enc}{q}"
        return f"action={q}{m.group('base')}?token={enc}{q}"

    return _ACTION_RE.sub(_sub, html)


class OpenUIBridge:
    """Deterministic sanitise → cap → store / rasterise pipeline (`specs/29-openui.md` §2.3)."""

    def __init__(self, *, store: OpenUIStore, signing_secret: str) -> None:
        """Bind the bridge to a store and HMAC secret.
        Args:
            store (OpenUIStore): Authoritative token/HTML store.
            signing_secret (str): Gateway-only signing material.
        Examples:
            >>> from sevn.ui.openui.store import OpenUIStore
            >>> import sqlite3
            >>> OpenUIBridge(store=OpenUIStore(sqlite3.connect(":memory:")), signing_secret="x")
            <...OpenUIBridge...>
        """
        self._store = store
        self._secret = signing_secret

    async def render(
        self,
        *,
        html: str,
        fallback_text: str,
        output: OutputMode,
        title: str | None,
        session_id: str,
        message_id: str,
        workspace_id: str,
        channel: str,
        trace: TraceSink,
        config: OpenUIConfig,
        runtime: OpenUIRuntimeDeps,
        rasterise_caps: RasteriseCaps | None = None,
        workspace_root: Path | None = None,
    ) -> OpenUIRenderResult:
        """Run the §2.3 pipeline and emit §7 trace events.
        Args:
            html (str): Agent-authored HTML (re-sanitised server-side).
            fallback_text (str): Plain-text fallback for failures and channel limits.
            output (OutputMode): ``live`` prefers iframe shell; ``screenshot`` / ``pdf`` force raster.
            title (str | None): Optional Telegram cover title metadata.
            session_id (str): Gateway session id.
            message_id (str): Correlating assistant / turn id.
            workspace_id (str): Workspace identifier for token payloads.
            channel (str): Active delivery channel (``webchat``, ``telegram``, …).
            trace (TraceSink): Trace sink for ``openui_*`` events.
            config (OpenUIConfig): Effective caps and TTL knobs.
            runtime (OpenUIRuntimeDeps): Public base URL and tunnel health snapshot.
            rasterise_caps (RasteriseCaps | None): Optional adapter raster budgets.
            workspace_root (Path | None): Workspace content root for artefact files.
        Returns:
            OpenUIRenderResult: Tokens, optional live URL / raster paths, and cap status.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(OpenUIBridge.render)
            True
        """
        t0 = time.perf_counter()
        caps = rasterise_caps or RasteriseCaps()
        base = runtime.public_base_url.strip().rstrip("/")

        async def _emit(kind: str, status: str, attrs: dict[str, object]) -> None:
            now = time.time_ns()
            if kind == "openui_render_error":
                from sevn.self_improve.openui_telemetry import record_openui_render_error

                record_openui_render_error(
                    workspace_id=workspace_id,
                    reason=str(attrs.get("kind", "unknown")),
                )
            await trace.emit(
                TraceEvent(
                    kind=kind,
                    span_id=uuid.uuid4().hex,
                    parent_span_id=None,
                    session_id=session_id,
                    turn_id=message_id,
                    tier=None,
                    ts_start_ns=now,
                    ts_end_ns=now,
                    status=status,
                    attrs=dict(attrs),
                ),
            )

        dropped_tags: list[str] = []
        sr = sanitise(html)
        for d in sr.dropped:
            if d.tag:
                dropped_tags.append(d.tag)
        if sr.dropped:
            await _emit(
                "openui_sanitise_diff",
                "ok",
                {
                    "session_id": session_id,
                    "message_id": message_id,
                    "dropped": [dd.model_dump() for dd in sr.dropped],
                },
            )
        post = sr.html or ""
        post_bytes = len(post.encode("utf-8"))
        cap_status: CapStatus = "ok"
        if post_bytes > config.hard_cap_bytes:
            await _emit(
                "openui_render_error",
                "error",
                {
                    "kind": "html_too_large",
                    "detail": "hard_cap",
                    "limit": config.hard_cap_bytes,
                    "actual": post_bytes,
                },
            )
            return OpenUIRenderResult(
                cap_status="hard_reject",
                fallback_text=fallback_text,
                error=OpenUIRenderError(
                    kind="html_too_large",
                    detail="post-sanitise HTML exceeds hard cap",
                    limits={"hard_cap_bytes": config.hard_cap_bytes, "actual": post_bytes},
                ),
                health_alert="OpenUI render failed: HTML exceeded hard byte cap",
            )
        if post_bytes > config.soft_cap_bytes:
            cap_status = "soft_warn"
        if not post.strip():
            await _emit(
                "openui_render_error",
                "error",
                {"kind": "sanitise_empty", "detail": "sanitiser removed all markup"},
            )
            return OpenUIRenderResult(
                cap_status=cap_status,
                fallback_text=fallback_text,
                error=OpenUIRenderError(
                    kind="sanitise_empty", detail="no HTML remains after sanitise"
                ),
                health_alert="OpenUI render failed: sanitiser produced empty HTML",
            )
        want_raster = output in ("screenshot", "pdf")
        if channel == "telegram" and not want_raster and not runtime.tunnel_healthy:
            want_raster = True
        record_id = secrets.token_urlsafe(16)
        exp_unix = int(time.time()) + int(config.token_ttl_seconds)
        exp_ns = int(time.time_ns()) + int(config.token_ttl_seconds) * 1_000_000_000
        render_tok = sign_token(
            secret=self._secret,
            workspace_id=workspace_id,
            session_id=session_id,
            message_id=message_id,
            record_id=record_id,
            scope="render",
            exp_unix=exp_unix,
        )
        submit_tok = sign_token(
            secret=self._secret,
            workspace_id=workspace_id,
            session_id=session_id,
            message_id=message_id,
            record_id=record_id,
            scope="submit",
            exp_unix=exp_unix,
        )
        html_for_store = inject_submit_token_into_html(post, submit_tok)
        rec = OpenUIRecord(
            record_id=record_id,
            workspace_id=workspace_id,
            session_id=session_id,
            message_id=message_id,
            channel=channel,
            sanitised_html=html_for_store,
            expires_at_ns=exp_ns,
            submit_consumed=False,
            fallback_text=fallback_text,
            extra={"title": title or ""},
        )
        if want_raster:
            img_path: str | None = None
            pdf_path: str | None = None
            if output == "pdf":
                blob = rasterise_pdf_bytes(html_for_store, base_url=base or None)
                if not blob or len(blob) > caps.pdf_max_bytes:
                    await _emit(
                        "openui_render_error",
                        "error",
                        {"kind": "rasterise_failed", "detail": "pdf empty or over cap"},
                    )
                    return OpenUIRenderResult(
                        cap_status=cap_status,
                        fallback_text=fallback_text,
                        error=OpenUIRenderError(kind="rasterise_failed", detail="pdf"),
                        health_alert="OpenUI render failed: PDF rasterise",
                    )
                pdf_path = _write_artifact(workspace_root, session_id, record_id, ".pdf", blob)
            else:
                blob = rasterise_png_bytes(html_for_store, base_url=base or None)
                if not blob or len(blob) > caps.png_max_bytes:
                    await _emit(
                        "openui_render_error",
                        "error",
                        {"kind": "rasterise_failed", "detail": "png empty or over cap"},
                    )
                    return OpenUIRenderResult(
                        cap_status=cap_status,
                        fallback_text=fallback_text,
                        error=OpenUIRenderError(kind="rasterise_failed", detail="png"),
                        health_alert="OpenUI render failed: PNG rasterise",
                    )
                img_path = _write_artifact(workspace_root, session_id, record_id, ".png", blob)
            self._store.put(rec)
            ms = int((time.perf_counter() - t0) * 1000)
            emit_status = "warn" if cap_status == "soft_warn" else "ok"
            await _emit(
                "openui_emit",
                emit_status,
                {
                    "session_id": session_id,
                    "message_id": message_id,
                    "output": output,
                    "bytes_in": sr.stats.get("bytes_in", 0),
                    "bytes_post_sanitise": post_bytes,
                    "dropped_tags": dropped_tags,
                    "token": render_tok[:16],
                    "cap_status": cap_status,
                },
            )
            await _emit(
                "openui_render",
                "ok",
                {
                    "live_url": "",
                    "image_path": img_path or "",
                    "pdf_path": pdf_path or "",
                    "duration_ms": ms,
                },
            )
            return OpenUIRenderResult(
                token=render_tok,
                submit_token=submit_tok,
                live_url=None,
                image_path=img_path,
                pdf_path=pdf_path,
                cap_status=cap_status,
                fallback_text=fallback_text,
            )
        # live path
        self._store.put(rec)
        live_url = f"{base}/openui/{render_tok}" if base else f"/openui/{render_tok}"
        ms = int((time.perf_counter() - t0) * 1000)
        emit_status = "warn" if cap_status == "soft_warn" else "ok"
        await _emit(
            "openui_emit",
            emit_status,
            {
                "session_id": session_id,
                "message_id": message_id,
                "output": output,
                "bytes_in": sr.stats.get("bytes_in", 0),
                "bytes_post_sanitise": post_bytes,
                "dropped_tags": dropped_tags,
                "token": render_tok[:16],
                "cap_status": cap_status,
            },
        )
        await _emit(
            "openui_render",
            "ok",
            {
                "live_url": live_url,
                "image_path": "",
                "pdf_path": "",
                "duration_ms": ms,
            },
        )
        return OpenUIRenderResult(
            token=render_tok,
            submit_token=submit_tok,
            live_url=live_url,
            cap_status=cap_status,
            fallback_text=fallback_text,
        )


def _write_artifact(
    workspace_root: Path | None,
    session_id: str,
    record_id: str,
    suffix: str,
    blob: bytes,
) -> str:
    """Persist raster bytes under the workspace artifact output directory.
    Args:
        workspace_root (Path | None): Workspace root; defaults to cwd when ``None``.
        session_id (str): Owning gateway session id.
        record_id (str): OpenUI record id used in the filename stem.
        suffix (str): File extension including leading dot (``.png`` / ``.pdf``).
        blob (bytes): Raster payload bytes.
    Returns:
        str: Absolute filesystem path of the written file.
    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> p = _write_artifact(root, "sid", "rid", ".bin", b"data")
        >>> Path(p).name
        'openui_rid.bin'
    """
    from sevn.config.loader import find_sevn_json, load_workspace
    from sevn.workspace.artifact_output import artifact_output_prefix

    root = workspace_root or Path(".")
    prefix = artifact_output_prefix(None, session_id)
    sj = find_sevn_json(root)
    if sj is not None:
        ws, _layout = load_workspace(sevn_json=sj)
        prefix = artifact_output_prefix(ws, session_id)
    target = root / prefix
    target.mkdir(parents=True, exist_ok=True)
    name = f"openui_{record_id}{suffix}"
    path = target / name
    path.write_bytes(blob)
    return str(path.resolve())


__all__ = ["OpenUIBridge", "build_content_security_policy", "inject_submit_token_into_html"]
