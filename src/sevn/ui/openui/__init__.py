"""OpenUI bridge, sanitiser, and gateway helpers (`specs/29-openui.md`).

Exports:
    OpenUIBridge — deterministic render pipeline.
    OpenUIRecord — one stored render payload.
    OpenUIStore — token/HTML persistence.
    build_content_security_policy — CSP header value for OpenUI shells.
    build_openui_delivery_metadata — map render results to outbound adapter metadata.
    build_openui_dispatch_payload — callback POST → :class:`IncomingMessage` kwargs.
    effective_openui_config — workspace → runtime config.
    inject_submit_token_into_html — inject submit token into form actions.
    openui_render — tier B/C/D tool body.
    parse_query_dict — URL-encoded form body parser.
    register_openui_tools — register ``openui_render`` on a :class:`ToolExecutor`.
    sanitise — HTML allowlist sanitiser.
    sign_token — mint HMAC render/submit token.
    verify_token — verify token and return payload or ``None``.
    verify_token_status — verify token with explicit status tuple.
"""

from __future__ import annotations

from sevn.ui.openui.bridge import (
    OpenUIBridge,
    build_content_security_policy,
    inject_submit_token_into_html,
)
from sevn.ui.openui.callback import build_openui_dispatch_payload, parse_query_dict
from sevn.ui.openui.delivery import build_openui_delivery_metadata
from sevn.ui.openui.models import effective_openui_config
from sevn.ui.openui.sanitiser import sanitise
from sevn.ui.openui.store import OpenUIRecord, OpenUIStore
from sevn.ui.openui.tokens import sign_token, verify_token, verify_token_status
from sevn.ui.openui.tools_register import openui_render, register_openui_tools

__all__ = [
    "OpenUIBridge",
    "OpenUIRecord",
    "OpenUIStore",
    "build_content_security_policy",
    "build_openui_delivery_metadata",
    "build_openui_dispatch_payload",
    "effective_openui_config",
    "inject_submit_token_into_html",
    "openui_render",
    "parse_query_dict",
    "register_openui_tools",
    "sanitise",
    "sign_token",
    "verify_token",
    "verify_token_status",
]
