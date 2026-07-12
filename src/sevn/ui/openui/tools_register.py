"""Register ``openui_render`` for tier B/C/D toolsets (`specs/29-openui.md` §2.1).

Module: sevn.ui.openui.tools_register
Depends: sevn.tools.*, sevn.ui.openui.bridge

Exports:
    openui_render — async tool body bound as ``openui_render`` (includes ``delivery_metadata``).
    register_openui_tools — attach :func:`openui_render` to a :class:`ToolExecutor`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from sevn.config.loader import find_sevn_json, load_workspace
from sevn.tools.base import ToolExecutor, enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.decorator import sevn_tool, tool_from_decorated
from sevn.ui.openui.bridge import OpenUIBridge
from sevn.ui.openui.delivery import build_openui_delivery_metadata
from sevn.ui.openui.models import (
    OpenUIRenderResult,
    OpenUIRuntimeDeps,
    effective_openui_config,
)
from sevn.ui.openui.store import OpenUIStore

if TYPE_CHECKING:
    from sevn.tools.context import ToolContext


@sevn_tool(
    name="openui_render",
    category="ui",
    description=(
        "Sanitise and publish agent-authored HTML via OpenUI (live URL or rasterised PNG/PDF). "
        "Requires fallback_text for delivery when sanitisation or rasterisation fails. "
        "For agent-authored HTML ONLY — do NOT use to download, save, or render an external "
        "or fetched web page; for that, use get_page_content then the `pdf` skill "
        "(run_skill_script scripts/pdf.py)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "html": {"type": "string", "description": "Agent-authored HTML fragment."},
            "fallback_text": {
                "type": "string",
                "description": "Plain-text fallback required on every emit.",
            },
            "output": {
                "type": "string",
                "enum": ["live", "screenshot", "pdf"],
                "default": "live",
            },
            "title": {"type": "string", "description": "Optional short Telegram cover title."},
        },
        "required": ["html", "fallback_text"],
    },
    abortable=False,
    sandbox_mode="none",
)
async def openui_render(
    ctx: ToolContext,
    html: str,
    fallback_text: str,
    output: Literal["live", "screenshot", "pdf"] = "live",
    title: str | None = None,
) -> str:
    """Invoke :class:`OpenUIBridge` using workspace config and optional gateway bridge (`specs/29-openui.md` §2.1).

    Args:
        ctx (ToolContext): Tool runtime (paths, trace, optional ``openui_bridge``).
        html (str): Agent-authored HTML fragment.
        fallback_text (str): Plain-text fallback when render fails.
        output (Literal["live", "screenshot", "pdf"]): Delivery mode.
        title (str | None): Optional short title for channel adapters.

    Returns:
        str: JSON tool envelope (success or validation failure).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(openui_render)
        True
    """

    sj = find_sevn_json(ctx.workspace_path)
    if sj is None:
        return json.dumps(
            {"ok": False, "error": "sevn.json not found", "spec": "specs/29-openui.md"},
            separators=(",", ":"),
        )
    ws, layout = load_workspace(sevn_json=sj)
    cfg = effective_openui_config(ws.openui)
    bridge: OpenUIBridge | None = getattr(ctx, "openui_bridge", None)
    if bridge is None:
        store = OpenUIStore(None)
        bridge = OpenUIBridge(
            store=store, signing_secret=f"dev-{ws.workspace_root}-{ctx.workspace_id}"
        )
    trace = ctx.trace
    if trace is None:
        from sevn.agent.tracing.sink import NullTraceSink

        trace = NullTraceSink()
    public = getattr(ctx, "gateway_public_base_url", None) or ""
    tunnel_healthy = bool(getattr(ctx, "tunnel_healthy", True))
    runtime = OpenUIRuntimeDeps(public_base_url=str(public), tunnel_healthy=tunnel_healthy)
    channel = getattr(ctx, "delivery_channel", None) or "webchat"
    msg_id = ctx.turn_id if ctx.turn_id and ctx.turn_id != "unset" else ctx.session_id
    out: OpenUIRenderResult = await bridge.render(
        html=html,
        fallback_text=fallback_text,
        output=output,
        title=title,
        session_id=ctx.session_id,
        message_id=msg_id,
        workspace_id=ctx.workspace_id,
        channel=str(channel),
        trace=trace,
        config=cfg,
        runtime=runtime,
        workspace_root=layout.content_root,
    )
    if out.error is not None:
        # Sanitiser removed all markup — deliver fallback_text cleanly (W6.1).
        if out.error.kind == "sanitise_empty" and out.fallback_text.strip():
            return enveloped_success(
                {
                    "fallback_text": out.fallback_text,
                    "sanitise_empty": True,
                    "delivery_mode": "text_fallback_only",
                    "cap_status": out.cap_status,
                    "instruction": (
                        "HTML sanitisation removed all markup. Do not claim a live UI, URL, "
                        "or image was rendered — deliver fallback_text as plain text only."
                    ),
                }
            )
        return enveloped_failure(
            out.error.detail or out.error.kind,
            code=ToolResultCode.VALIDATION_ERROR,
            data={"openui": out.model_dump(mode="json")},
        )
    payload = out.model_dump(mode="json")
    payload["delivery_metadata"] = build_openui_delivery_metadata(
        out,
        channel=str(channel),
        title=title,
        safe_origin=str(public).rstrip("/") if public else "",
    )
    return enveloped_success(payload)


def register_openui_tools(executor: ToolExecutor) -> None:
    """Register :func:`openui_render` (always on for B/C/D per spec).

    Args:
        executor (ToolExecutor): Registry receiving the decorated tool.

    Returns:
        None: Mutates ``executor`` in place.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> ex = ToolExecutor(default_timeout_seconds=None)
        >>> register_openui_tools(ex)
        >>> "openui_render" in ex._tools
        True
    """

    executor.register(tool_from_decorated(openui_render))


__all__ = ["openui_render", "register_openui_tools"]
